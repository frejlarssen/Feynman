import pendulum
from kubernetes.client import models as k8s

from airflow.providers.cncf.kubernetes.operators.pod import KubernetesPodOperator
from airflow.sdk import dag, task


KUBECONFIG = "/home/frej/.kube/config"
DATA_MOUNT_PATH = "/data"

DATA_VOLUME_MOUNT = k8s.V1VolumeMount(
    name="feynman-data",
    mount_path=DATA_MOUNT_PATH,
)

DATA_VOLUME = k8s.V1Volume(
    name="feynman-data",
    host_path=k8s.V1HostPathVolumeSource(
        path=DATA_MOUNT_PATH,
        type="Directory",
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
    Orchestrates batch simulation with Airflow TaskFlow and one Kubernetes pod
    per batch.
    """

    @task()
    def split_output_into_batches(output_hexstrings_filename: str) -> list[list[str]]:
        """
        #### Split into batches
        Placeholder for splitting the output hexstrings file and returning one
        simulator argument list per batch.
        """

        num_batches = 5
        batch_arguments = []

        for batch_id in range(num_batches):
            batch_file = f"{DATA_MOUNT_PATH}/generated/batches/batch_{batch_id}.hs"
            output_file = (
                f"{DATA_MOUNT_PATH}/outputs/tmp/qft_n8_k2_batch_{batch_id}.hsv"
            )
            batch_arguments.append(
                [
                    "-c",
                    f"{DATA_MOUNT_PATH}/generated/circuits/qft/qft_n8_k2.qasm",
                    "-i",
                    f"{DATA_MOUNT_PATH}/generated/statevectors/ket0_size1.hsv",
                    "-b",
                    batch_file,
                    "-o",
                    output_file,
                    "-t",
                    "0.0",
                    "-v",
                    "1",
                ]
            )

        print(
            f"Prepared {num_batches} batch pod argument lists from "
            f"{output_hexstrings_filename}."
        )
        return batch_arguments

    @task()
    def concatenate() -> str:
        # Real implementation should concatenate the batch output files on shared storage.
        print("Concatenation succeeded.")
        return f"{DATA_MOUNT_PATH}/outputs/tmp/qft_n8_k2_all_batches.hsv"

    @task()
    def postprocessing(concatenated_output_file: str) -> bool:
        # Real implementation can compute observables, plots, and summaries.
        print(f"Post-processing succeeded for {concatenated_output_file}.")
        return True

    batch_arguments = split_output_into_batches(
        f"{DATA_MOUNT_PATH}/generated/hexstring_sets/"
        "nrhex10_size1_from0x0_to0xA.hs"
    )

    simulate_batches = KubernetesPodOperator.partial(
        task_id="simulate_batch",
        name="simulate-batch",
        image="feynman:latest",
        image_pull_policy="Never",
        config_file=KUBECONFIG,
        get_logs=True,
        on_finish_action="delete_pod",
        volume_mounts=[DATA_VOLUME_MOUNT],
        volumes=[DATA_VOLUME],
    ).expand(arguments=batch_arguments)

    concatenated_output_file = concatenate()
    simulate_batches >> concatenated_output_file

    postprocessing(concatenated_output_file)


feynman()
