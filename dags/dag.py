from datetime import timedelta, datetime

import pendulum
from airflow import DAG
from airflow.operators.bash_operator import BashOperator

default_args = {
    'owner': 'airflow',
    'depends_on_past': False,
    'email': ['ax66@@bk.com'],
    'email_on_failure': True,
    'email_on_retry': True,
    'retries': 0,
    'retry_delay': timedelta(minutes=5),
    # 'queue': 'bash_queue',
    # 'pool': 'backfill',
    # 'priority_weight': 10,
    # 'end_date': datetime(2016, 1, 1),
    # 'wait_for_downstream': False,
    # 'dag': dag,
    # 'sla': timedelta(hours=2),
    # 'execution_timeout': timedelta(seconds=300),
    # 'on_failure_callback': some_function,
    # 'on_success_callback': some_other_function,
    # 'on_retry_callback': another_function,
    # 'sla_miss_callback': yet_another_function,
    # 'trigger_rule': 'all_success'
}
schedule_interval = timedelta(hours=1)
start_date = datetime.now(tz=pendulum.timezone('Europe/Moscow')).replace(hour=6, minute=0) - schedule_interval

dag = DAG('proxy_crawler',
          catchup=False,
          default_args=default_args,
          description='proxy crawler',
          tags=['test'],
          schedule_interval=schedule_interval,
          start_date=start_date,

          )
t1 = BashOperator(
    task_id='run_igoods',
    bash_command='cd /app && pip install -e . && cd examples && python collector.py',
    dag=dag,
)
