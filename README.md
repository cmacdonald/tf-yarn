tf-skein
========

<img src="https://gitlab.criteois.com/s.lebedev/tf-skein/raw/master/skein.png"
    width="40%" />


Installation
------------

Make sure you have Python 3.6+ and Maven (required by Skein) available and then
run:

```bash
$ pip install git+https://github.com/criteo-forks/skein#egg=criteo-forks-skein
$ pip install git+https://gitlab.criteois.com/s.lebedev/tf-skein.git
```

<!-- Uncomment once upstream PRs to skein are merged.

```bash
$ pip install git+https://gitlab.criteois.com/s.lebedev/tf-skein.git
```
-->


Quickstart
----------

The core abstraction in `tf-skein` is called an `ExperimentFn`. It is
a function returning a triple of an `Estimator`, and two specs --
`TrainSpec` and `EvalSpec`.

Here is a stripped down `experiment_fn` from
[`examples/cpu_example.py`](examples/cpu_example.py) to give you an idea of how
it might look:

``` python
from tf_skein import Experiment

def experiment_fn():
    # ...
    estimator = tf.estimator.DNNClassifier(...)
    return Experiment(
        estimator,
        tf.estimator.TrainSpec(train_input_fn),
        tf.estimator.EvalSpec(eval_input_fn)
```

The experiment can be scheduled on YARN using the `run_on_yarn` function which
takes two required arguments: an `experimeng_fn`, and a dictionary specifying
how much resources to allocate for each of the distributed TensorFlow task
types. The dataset in `examples/cpu_example.py` is tiny and does not need
multi-node training. Therefore, it can be scheduled using just the `"chief"` and
`"evaluator"` tasks. Each task will be executed in its own container.

```python
from tf_skein import run_on_yarn, TaskSpec

run_on_yarn(
    experiment_fn,
    task_specs={
        "chief": TaskSpec(memory=2 * 2**10, vcores=4),
        "evaluator": TaskSpec(memory=2**10, vcores=1)
    }
)
```

The final bit is to forward the Python dependencies of `cpy_example.py` to the
YARN containers, in order for the chief and evaluator to be able to import it:

```python
run_on_yarn(
    ...,
    files={
        os.path.basename(winequality.__file__): winequality.__file__,
        os.path.basename(experiment_fn.__file__): experiment_fn.__file__,
    }
)
```

The full example can be ran as follows:

```bash
$ ./run_example.sh examples/cpu_example.py
```

<!--
TODO: A more elaborate configuration involving a `"ps"` and multiple `"worker"`
tasks might look like:

```python
cluster.run(experiment_fn, task_specs={
    "chief": TaskSpec(memory=2 * 2**10, vcores=4),
    "worker": TaskSpec(memory=2 * 2**10, vcores=4, instances=2),
    "ps": TaskSpec(memory=2 * 2**10, vcores=1),
    "evaluator": TaskSpec(memory=2**10, vcores=1)
})
```
-->

### Distributed TensorFlow 101

This is a brief summary of the core distributed TensorFlow concepts. Please
refer to the [official documentation][distributed-tf] for the full version.

Distributed TensorFlow operates in terms of tasks. A task has a type which
defines its purpose in the distributed TensorFlow cluster. ``"worker"`` tasks
headed by the `"chief"` do model training. The `"chief"` additionally handles
checkpointing, saving/restoring the model, etc. The model itself is stored
on one or more `"ps"` tasks. These tasks typically do not compute anything.
Their sole purpose is serving the variables of the model. Finally, the
`"evaluator"` task is responsible for periodically evaluating the model.

At the minimum, the cluster must have a single `"chief"` task. However, it
is a good idea to complement it by the `"evaluator"` to allow for running
the evaluation in parallel with the training.

```
+-----------+              +-------+   +----------+   +----------+
| evaluator |        +-----+ chief |   | worker:0 |   | worker:1 |
+-----+-----+        |     +----^--+   +-----^----+   +-----^----+
      ^              |          |            |              |
      |              v          |            |              |
      |        +-----+---+      |            |              |
      |        | model   |   +--v---+        |              |
      +--------+ exports |   | ps:0 <--------+--------------+
               +---------+   +------+
```

### Configuring the Python interpreter and packages

`tf-skein` ships an isolated Python environment to the containers. By default
it comes with a Python interpreter, TensorFlow, and a few of the `tf-skein`
dependencies (see `requirements.txt` for the full list).

Additional pip-installable packages can be added via the `pip_packages` argument
to `run_on_yarn`:

```python
run_on_yarn(
    ...,
    pip_packages=["keras"]
)
```

### Running on GPU@Criteo

By default `run_on_yarn` runs an experiment on CPU-only nodes. To run on GPU
on the pa4.preprod cluster:

1. Set the `"queue"` argument to `run_on_yarn` to `"ml-gpu"`.
2. Set `TaskSpec.flavor` to `TaskFlavor.GPU` for relevant task types. In
   general, it is a good idea to run compute heavy `"chief"`, `"worker"`
   tasks on GPU, while keeping `"ps"` and `"evaluator"` on CPU.

Relevant part of [examples/gpu_example.py](examples/gpu_example.py):

```python
from tf_skein import run_on_yarn, TaskFlavor

run_on_yarn(
    experiment_fn,
    task_specs={
        "chief": TaskSpec(memory=2 * 2**10, vcores=4, flavor=TaskFlavor.GPU),
        "evaluator": TaskSpec(memory=2**10, vcores=1)
    },
    queue="ml-gpu"
)
```

Limitations
-----------

### Using `tf-skein` on Windows/macOS

`tf-skein` uses [Miniconda][miniconda] for creating relocatable
Python environments. The package management, however, is done by
pip to allow for more flexibility. The downside to that is that
it is impossible to create an environment for an OS/architecture
different from the one the library is running on.

<!-- TODO: assume Python is installed and use PEX? -->

### TensorBoard

`tf-skein` does not currently integrate with TensorBoard, even though
the only requirement for doing so, `model_dir`, is already exposed
via `Experiment.config`.

[miniconda]: https://conda.io/miniconda.html
[tf-estimators]: https://www.tensorflow.org/guide/estimators
[distributed-tf]: https://www.tensorflow.org/deploy/distributed
[skein]: https://jcrist.github.io/skein
[skein-tutorial]: https://jcrist.github.io/skein/quickstart.html
