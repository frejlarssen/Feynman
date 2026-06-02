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
    def split_output_into_batches(output_hexstrings_filename: str):
        """
        #### Split into batches
        Read output hexstrings and split them into batches.
        The batches are labeled `batch_i.hs`, where i is the number of the batch.
        """

        # Should we do this right here in python or have a Kubernates pod do it?
        # Read output_hexstrings_filename
        # Write batches to the same shared filesystem

        num_batches = 42 #Placeholder
        batch_ids = range(num_batches)
        return batch_ids

    @task_group
    def process_batch(batch_id: int):
        # Maybe task group is unnecessary. The what we expand on could be one pod.

        @task()
        def simulate(batch_id: int):
            # Kubernates container with docker image.

            # Reads input hexstrings
            # Reads and parses circuit
            # Simulates and sums over all input hexstrings

            # The result is a list of (hexstring, amplitude) paris.
            # Can this be passed as XComm?
            # Or better to write one file per batch and then concatenate in postprocessing?
            result : list[tuple[str, tuple[float, float]]] = []

            status = True # Did it succeed or not? Reduce on these.
            return status

        return simulate(batch_id)
    
    @task()
    def concatenate(status):
        if status == True:
            # Concatenate output files of the batches
            return True
        else:
            return False
    
    @task()
    def postprocessing(status):
        if status == True:
            # Calculate observables, generate plots, etc. Could be python or C++.
            return True
        else:
            return False

    batch_ids = split_output_into_batches("output_hexstrings.hs")

    status = process_batch.expand(batch_id = batch_ids) #TODO: Reduce the status to one single status.

    status = concatenate(status)
    postprocessing(status)

feynman()