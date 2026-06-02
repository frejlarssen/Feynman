import pendulum

from airflow.sdk import dag, task
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
    pass
feynman()