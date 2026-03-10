"""
SageMaker Pipeline Definition
5-step DAG: ProcessData → FeatureStore → Train → Evaluate → Register
Auto-triggered from S3 EventBridge when new race data lands.
"""
import boto3
import sagemaker
from sagemaker.workflow.pipeline import Pipeline
from sagemaker.workflow.steps import ProcessingStep, TrainingStep
from sagemaker.workflow.step_collections import RegisterModel
from sagemaker.workflow.condition_step import ConditionStep
from sagemaker.workflow.conditions import ConditionGreaterThanOrEqualTo
from sagemaker.workflow.functions import JsonGet
from sagemaker.workflow.parameters import ParameterString
from sagemaker.sklearn.processing import SKLearnProcessor
from sagemaker.sklearn.estimator import SKLearn
from sagemaker.processing import ProcessingInput, ProcessingOutput
from sagemaker.inputs import TrainingInput
from sagemaker.model_metrics import MetricsSource, ModelMetrics
import os

AWS_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
ACCOUNT_ID = os.environ.get("AWS_ACCOUNT_ID", "297997106614")
PROJECT = "f1-mlops"

session = sagemaker.Session(boto_session=boto3.Session(region_name=AWS_REGION))
role = f"arn:aws:iam::{ACCOUNT_ID}:role/{PROJECT}-sagemaker-role"
bucket = f"{PROJECT}-data-{ACCOUNT_ID}"

# Pipeline parameters
input_data_url = ParameterString(name="InputDataUrl", default_value=f"s3://{bucket}/processed/pitstop/")
model_output_url = ParameterString(name="ModelOutputUrl", default_value=f"s3://{bucket}/models/")


def create_pipeline() -> Pipeline:
    # Step 1: ProcessData — data validation and feature prep
    sklearn_processor = SKLearnProcessor(
        framework_version="1.2-1",
        role=role,
        instance_type="ml.m5.large",
        instance_count=1,
        sagemaker_session=session,
    )

    process_step = ProcessingStep(
        name="ProcessData",
        processor=sklearn_processor,
        inputs=[
            ProcessingInput(
                source=input_data_url,
                destination="/opt/ml/processing/input",
            )
        ],
        outputs=[
            ProcessingOutput(
                output_name="train",
                source="/opt/ml/processing/train",
                destination=f"s3://{bucket}/processed/split/train/",
            ),
            ProcessingOutput(
                output_name="validation",
                source="/opt/ml/processing/validation",
                destination=f"s3://{bucket}/processed/split/validation/",
            ),
        ],
        code="ml/evaluation/preprocess.py",
    )

    # Step 2: Train — XGBoost pitstop model
    xgb_estimator = SKLearn(
        entry_point="train.py",
        source_dir="ml/training/pitstop",
        role=role,
        instance_type="ml.m5.xlarge",
        instance_count=1,
        framework_version="1.2-1",
        py_version="py3",
        sagemaker_session=session,
        output_path=f"s3://{bucket}/models/pitstop/",
        hyperparameters={
            "n-estimators": 300,
            "max-depth": 6,
            "learning-rate": 0.05,
        },
    )

    train_step = TrainingStep(
        name="TrainPitstopModel",
        estimator=xgb_estimator,
        inputs={
            "training": TrainingInput(
                s3_data=process_step.properties.ProcessingOutputConfig.Outputs["train"].S3Output.S3Uri,
                content_type="text/csv",
            )
        },
    )

    # Step 3: Evaluate — check AUC >= 0.82
    eval_processor = SKLearnProcessor(
        framework_version="1.2-1",
        role=role,
        instance_type="ml.m5.large",
        instance_count=1,
        sagemaker_session=session,
    )

    eval_step = ProcessingStep(
        name="EvaluateModel",
        processor=eval_processor,
        inputs=[
            ProcessingInput(
                source=train_step.properties.ModelArtifacts.S3ModelArtifacts,
                destination="/opt/ml/processing/model",
            ),
            ProcessingInput(
                source=process_step.properties.ProcessingOutputConfig.Outputs["validation"].S3Output.S3Uri,
                destination="/opt/ml/processing/validation",
            ),
        ],
        outputs=[
            ProcessingOutput(
                output_name="evaluation",
                source="/opt/ml/processing/evaluation",
                destination=f"s3://{bucket}/models/pitstop/evaluation/",
            )
        ],
        code="ml/evaluation/evaluate.py",
        property_files=[
            sagemaker.workflow.properties.PropertyFile(
                name="EvaluationReport",
                output_name="evaluation",
                path="evaluation.json",
            )
        ],
    )

    # Step 4: Register — only if AUC >= 0.82
    model_metrics = ModelMetrics(
        model_statistics=MetricsSource(
            s3_uri=f"{eval_step.arguments['ProcessingOutputConfig']['Outputs'][0]['S3Output']['S3Uri']}/evaluation.json",
            content_type="application/json",
        )
    )

    register_step = RegisterModel(
        name="RegisterPitstopModel",
        estimator=xgb_estimator,
        model_data=train_step.properties.ModelArtifacts.S3ModelArtifacts,
        content_types=["application/json"],
        response_types=["application/json"],
        inference_instances=["ml.m5.large"],
        transform_instances=["ml.m5.large"],
        model_package_group_name=f"{PROJECT}-pitstop",
        approval_status="Approved",
        model_metrics=model_metrics,
    )

    # Step 5: ConditionStep — gate registration on AUC
    auc_condition = ConditionGreaterThanOrEqualTo(
        left=JsonGet(
            step_name=eval_step.name,
            property_file="EvaluationReport",
            json_path="auc",
        ),
        right=0.82,
    )

    condition_step = ConditionStep(
        name="CheckAUC",
        conditions=[auc_condition],
        if_steps=[register_step],
        else_steps=[],  # No registration if AUC < 0.82
    )

    pipeline = Pipeline(
        name=f"{PROJECT}-training-pipeline",
        parameters=[input_data_url, model_output_url],
        steps=[process_step, train_step, eval_step, condition_step],
        sagemaker_session=session,
    )

    return pipeline


if __name__ == "__main__":
    pipeline = create_pipeline()
    pipeline.upsert(role_arn=role)
    print(f"Pipeline '{pipeline.name}' upserted successfully.")
