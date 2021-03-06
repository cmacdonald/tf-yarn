from unittest import mock
from tf_yarn import (
    _run_on_cluster,
    _setup_cluster_tasks,
    get_safe_experiment_fn,
    SkeinCluster,
    Experiment,
    run_on_yarn
)
import skein
import pytest
import tensorflow as tf
from tf_yarn.topologies import TaskSpec


sock_addrs = {
    'chief': ['addr1:port1', 'addr10:port10', 'addr11:port11'],
    'evaluator': ['addr2:port2', 'addr3:port3'],
    'ps': ['addr4:port4', 'addr5:port5', 'addr6:port6'],
    'worker': ['addr7:port7', 'addr8:port8', 'addr9:port9']
}


@mock.patch("tf_yarn.skein.ApplicationClient")
@pytest.mark.parametrize("tasks_instances, expected_spec, standalone_client_mode", [
    ([('chief', 1), ('evaluator', 1), ('ps', 1), ('worker', 3)],
     {'chief': ['addr1:port1'],
      'ps': ['addr4:port4'],
      'worker': ['addr7:port7', 'addr8:port8', 'addr9:port9']
      },
     False
     ),
    ([('chief', 3)],
     {'chief': ['addr1:port1', 'addr10:port10', 'addr11:port11']},
     False
     ),
    ([('worker', 3), ('ps', 3)],
     {'worker': ['addr7:port7', 'addr8:port8', 'addr9:port9'],
      'ps': ['addr4:port4', 'addr5:port5', 'addr6:port6']
      },
     False
     ),
    ([('worker', 1), ('evaluator', 0)],
     {'worker': ['addr7:port7']},
     False
     ),
    ([('chief', 1), ('evaluator', 1), ('ps', 1), ('worker', 3)],
     {'ps': ['addr4:port4'],
      'worker': ['addr7:port7', 'addr8:port8', 'addr9:port9']
      },
     True
     )
])
def test__setup_cluster_tasks(
        mock_skein_app,
        tasks_instances,
        expected_spec,
        standalone_client_mode):
    kv_store = dict()
    for task_type, nb_instances in tasks_instances:
        for i in range(nb_instances):
            kv_store[f'{task_type}:{i}/init'] = sock_addrs[task_type][i].encode()

    mock_skein_app.kv.wait = kv_store.get
    cluster_spec = _setup_cluster_tasks(tasks_instances,
                                        mock_skein_app,
                                        standalone_client_mode)

    assert cluster_spec.as_dict() == expected_spec


def test_kill_skein_on_exception():
    def cloudpickle_raise_exception(*args, **kwargs):
        raise Exception("Cannot serialize your method!")

    with mock.patch('tf_yarn._setup_pyenvs'):
        with mock.patch('tf_yarn.cloudpickle.dumps') as mock_cloudpickle:
            mock_cloudpickle.side_effect = cloudpickle_raise_exception
            mock_app = mock.MagicMock(skein.ApplicationClient)
            cluster = SkeinCluster(
                client=None, app=mock_app, cluster_spec=dict(),
                event_listener=None, events=None, tasks=[])
            try:
                _run_on_cluster(lambda: None, cluster)
            except Exception:
                pass
            mock_app.shutdown.assert_called_once_with(
                skein.model.FinalStatus.FAILED)


def _experiment_fn(model_dir):
    print(f"create experiment with model_dir={model_dir}")

    def model_fn():
        return tf.estimator.EstimatorSpec()

    def train_fn():
        return None

    def eval_fn():
        return None

    return Experiment(
        tf.estimator.LinearClassifier(feature_columns=[], model_dir=model_dir),
        tf.estimator.TrainSpec(train_fn),
        tf.estimator.EvalSpec(eval_fn))


def test_get_safe_experiment_fn():
    with mock.patch('importlib.import_module') as mock_import_module:
        module = mock.Mock()
        module.experiment_fn = _experiment_fn
        mock_import_module.return_value = module
        experiment_fn = get_safe_experiment_fn("testpackage.testmodule.experiment_fn",
                                               "test_model_dir")
        print(f"got function .. {experiment_fn}")
        print(f"execute function ..")
        print(experiment_fn)
        experiment = experiment_fn()
        print(experiment)
        assert isinstance(experiment, Experiment) is True
        assert experiment.estimator.model_dir == "test_model_dir"
        mock_import_module.assert_called_once_with("testpackage.testmodule")


@pytest.mark.parametrize("nb_retries,nb_failures", [(0, 0), (1, 0), (1, 1), (2, 2)])
def test_retry_run_on_yarn(nb_retries, nb_failures):
    cpt = 0

    def fail(*args, **kwargs):
        if cpt < nb_failures:
            raise Exception("")
        else:
            pass

    with mock.patch('tf_yarn._setup_pyenvs'), \
            mock.patch('tf_yarn._setup_skein_cluster') as mock_setup_skein_cluster, \
            mock.patch('tf_yarn._run_on_cluster') as mock_run_on_cluster:
        mock_run_on_cluster.side_effect = fail

        gb = 2**10

        try:
            run_on_yarn(
                "path/to/env", lambda: Experiment(None, None, None),
                task_specs={
                    "chief": TaskSpec(memory=16 * gb, vcores=16),
                    "worker": TaskSpec(memory=16 * gb, vcores=16, instances=1),
                    "ps": TaskSpec(memory=16 * gb, vcores=16, instances=1)
                },
                nb_retries=nb_retries
            )
        except Exception:
            pass

        nb_calls = min(nb_retries, nb_failures) + 1
        assert mock_run_on_cluster.call_count == nb_calls
        assert mock_setup_skein_cluster.call_count == nb_calls
