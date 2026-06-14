import pendulum
from kubernetes.client import models as k8s

from airflow.providers.cncf.kubernetes.operators.pod import KubernetesPodOperator
from airflow.sdk import dag, task


KUBECONFIG = "/home/frej/.kube/config"
DATA_MOUNT_PATH = "/data"
DATA_PVC_NAME = "feynman-data-pvc"
HEXSTRINGS_FILE = (
    f"{DATA_MOUNT_PATH}/generated/hexstring_sets/nrhex10_size1_from0x0_to0xA.hs"
)
SPLIT_IMAGE = "feynman-split:latest"
SIMULATE_IMAGE = "feynman-simulate:latest"
CONCAT_IMAGE = "feynman-concat:latest"
NUM_BATCHES = 5

DATA_VOLUME_MOUNT = k8s.V1VolumeMount(
    name="feynman-data",
    mount_path=DATA_MOUNT_PATH,
)

DATA_VOLUME = k8s.V1Volume(
    name="feynman-data",
    persistent_volume_claim=k8s.V1PersistentVolumeClaimVolumeSource(
        claim_name=DATA_PVC_NAME,
    ),
)


@dag(
    schedule=None,
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    tags=["feynman"],
)
def feynman():
    """
    ### Feynman DAG
    Orchestrates simulation over batched hexstrings with one PVC-backed pod per
    pipeline stage.
    """

    @task()
    def build_batch_arguments(num_batches: int) -> list[list[str]]:
        batch_arguments = []

        for batch_id in range(num_batches):
            hexstrings_batch_file = (
                f"{DATA_MOUNT_PATH}/generated/batches/batch_{batch_id}.hs"
            )
            simulator_output_file = (
                f"{DATA_MOUNT_PATH}/outputs/tmp/qft_n8_k2_batch_{batch_id}.hsv"
            )
            batch_arguments.append(
                [
                    "-c",
                    f"{DATA_MOUNT_PATH}/generated/circuits/qft/qft_n8_k2.qasm",
                    "-i",
                    f"{DATA_MOUNT_PATH}/generated/statevectors/ket0_size1.hsv",
                    "-b",
                    hexstrings_batch_file,
                    "-o",
                    simulator_output_file,
                    "-t",
                    "0.0",
                    "-v",
                    "1",
                ]
            )

        print(f"Prepared {num_batches} simulation argument lists from batch files.")
        return batch_arguments

    split_hexstrings = KubernetesPodOperator(
        task_id="split_hexstrings",
        name="split-hexstrings",
        image=SPLIT_IMAGE,
        image_pull_policy="Never",
        config_file=KUBECONFIG,
        get_logs=True,
        on_finish_action="delete_pod",
        volume_mounts=[DATA_VOLUME_MOUNT],
        volumes=[DATA_VOLUME],
        arguments=[
            "-h",
            HEXSTRINGS_FILE,
            "-o",
            f"{DATA_MOUNT_PATH}/generated/batches",
            "-n",
            "2",
            "-v",
            "1",
        ],
    )

    batch_arguments = build_batch_arguments(NUM_BATCHES)

    simulate_batches = KubernetesPodOperator.partial(
        task_id="simulate_batch",
        name="simulate-batch",
        image=SIMULATE_IMAGE,
        image_pull_policy="Never",
        config_file=KUBECONFIG,
        get_logs=True,
        on_finish_action="delete_pod",
        volume_mounts=[DATA_VOLUME_MOUNT],
        volumes=[DATA_VOLUME],
    ).expand(arguments=batch_arguments)

    concatenate_batches = KubernetesPodOperator(
        task_id="concatenate_batches",
        name="concatenate-batches",
        image=CONCAT_IMAGE,
        image_pull_policy="Never",
        config_file=KUBECONFIG,
        get_logs=True,
        on_finish_action="delete_pod",
        volume_mounts=[DATA_VOLUME_MOUNT],
        volumes=[DATA_VOLUME],
        arguments=[
            "-i",
            f"{DATA_MOUNT_PATH}/outputs/tmp",
            "-o",
            f"{DATA_MOUNT_PATH}/outputs/tmp/qft_n8_k2_all_batches.hsv",
            "-v",
            "1",
        ],
    )

    @task()
    def postprocessing() -> bool:
        merged_simulator_output_file = (
            f"{DATA_MOUNT_PATH}/outputs/tmp/qft_n8_k2_all_batches.hsv"
        )
        print(f"Post-processing succeeded for {merged_simulator_output_file}.")
        return True

    split_hexstrings >> batch_arguments
    batch_arguments >> simulate_batches
    simulate_batches >> concatenate_batches
    concatenate_batches >> postprocessing()


feynman()
