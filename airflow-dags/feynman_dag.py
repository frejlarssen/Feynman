import pendulum

from airflow.sdk import dag, task, task_group
@dag(
    schedule=None,
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    tags=["feynman"],
)
def feynman():
    """
    ### Feynman DAG
    The DAG of the Feynman simulator
    """

    @task()
    def split_output_into_batches(output_bitstrings_filename: str):
        """
        #### Split into batches
        Read output bitstrings and split them into batches.
        The batches are labeled `batch_i.hs`, where i is the number of the batch.
        """

        # Should we do this right here in python or have a Kubernates pod do it?
        # Read output_bitstrings_filename
        # Write batches to the same shared filesystem

        num_batches = 42 #Placeholder
        batch_ids = range(num_batches)
        return batch_ids

    @task_group
    def process_batch(batch_id: int):
        # Maybe task group is unnecessary. The task we do expand on could be one pod.

        @task()
        def read_inputs():
            pass

        @task()
        def simulate(batch_id: int):
            pass

        # Kubernates container with docker image. Include read_inputs here also?
        return simulate(read_inputs())

    batch_ids = split_output_into_batches("output_hexstrings.hs")

    process_batch.expand(batch_id = batch_ids)

feynman()