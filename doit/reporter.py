"""Reports doit execution status/results"""

import sys
import time
import datetime
import json
from io import StringIO

from .exceptions import BaseFail


class ConsoleReporter:
    """Default reporter. print results on console/terminal (stdout/stderr)

    @ivar failure_verbosity: (int) include captured stdout/stderr on failure
                             report even if already shown.
    """
    # short description, used by the help system
    desc = 'console output'

    def __init__(self, outstream, options):
        # save non-successful result information (include task errors)
        self.failures = []
        self.runtime_errors = []
        self.failure_verbosity = options.get('failure_verbosity', 0)
        self.outstream = outstream

    def write(self, text):
        self.outstream.write(text)

    def initialize(self, tasks, selected_tasks):
        """called just after tasks have been loaded before execution starts"""
        pass


    def update_total(self, new_tasks):
        """called when new tasks are added to the graph after the initial
        load -- i.e. when a @create_after delayed task-creator gets
        expanded (see TaskDispatcher._add_task). `new_tasks` is the list of
        newly created Task objects, generated in one batch ahead of their
        individual selection/execution -- unlike get_status(), which only
        fires one task at a time, interleaved with that same task's
        selection, this is the only hook that can report an accurate
        growing total before those tasks are themselves resolved."""
        pass


    def get_status(self, task):
        """called when task is selected (check if up-to-date)"""
        pass

    def execute_task(self, task):
        """called when execution starts"""
        # ignore tasks that do not define actions
        # ignore private/hidden tasks (tasks that start with an underscore)
        if task.actions and (task.name[0] != '_'):
            self.write('.  %s\n' % task.title())

    def add_failure(self, task, fail: BaseFail):
        """called when execution finishes with a failure"""
        result = {'task': task, 'exception': fail}
        if fail.report:
            self.failures.append(result)
            self._write_failure(result)

    def add_success(self, task):
        """called when execution finishes successfully"""
        pass

    def skip_uptodate(self, task):
        """skipped up-to-date task"""
        if task.name[0] != '_':
            self.write("-- %s\n" % task.title())

    def skip_ignore(self, task):
        """skipped ignored task"""
        self.write("!! %s\n" % task.title())

    def cleanup_error(self, exception):
        """error during cleanup"""
        sys.stderr.write(exception.get_msg())

    def runtime_error(self, msg):
        """error from doit (not from a task execution)"""
        # saved so they are displayed after task failures messages
        self.runtime_errors.append(msg)

    def teardown_task(self, task):
        """called when starts the execution of teardown action"""
        pass


    def _write_failure(self, result, write_exception=True):
        msg = '%s - taskid:%s\n' % (result['exception'].get_name(),
                                    result['task'].name)
        self.write(msg)
        if write_exception:
            self.write(result['exception'].get_msg())
            self.write("\n")

    def complete_run(self):
        """called when finished running all tasks"""
        # if test fails print output from failed task
        for result in self.failures:
            task = result['task']
            # makes no sense to print output if task was not executed
            if not task.executed:
                continue
            show_err = task.verbosity < 1 or self.failure_verbosity > 0
            show_out = task.verbosity < 2 or self.failure_verbosity == 2
            if show_err or show_out:
                self.write("#" * 40 + "\n")
            if show_err:
                self._write_failure(result,
                                    write_exception=self.failure_verbosity)
                err = "".join([a.err for a in task.actions if a.err])
                self.write("{} <stderr>:\n{}\n".format(task.name, err))
            if show_out:
                out = "".join([a.out for a in task.actions if a.out])
                self.write("{} <stdout>:\n{}\n".format(task.name, out))

        if self.runtime_errors:
            self.write("#" * 40 + "\n")
            self.write("Execution aborted.\n")
            self.write("\n".join(self.runtime_errors))
            self.write("\n")


class ExecutedOnlyReporter(ConsoleReporter):
    """No output for skipped (up-to-date) and group tasks

    Produces zero output unless a task is executed
    """
    desc = 'console, no output for skipped (up-to-date) and group tasks'

    def skip_uptodate(self, task):
        """skipped up-to-date task"""
        pass

    def skip_ignore(self, task):
        """skipped ignored task"""
        pass



class ZeroReporter(ConsoleReporter):
    """Report only internal errors from doit"""
    desc = 'report only internal errors from doit'

    def _just_pass(self, *args):
        """over-write base to do nothing"""
        pass

    get_status = execute_task = add_failure = add_success \
        = skip_uptodate = skip_ignore = teardown_task = complete_run \
        = _just_pass

    def runtime_error(self, msg):
        sys.stderr.write(msg)


class ErrorOnlyReporter(ZeroReporter):
    desc = """Report only errors internal or TaskError and TaskFailure."""

    def add_failure(self, task, fail_info: BaseFail):
        if not fail_info.report:
            return
        exception_name = fail_info.get_name()
        self.write(f'taskid:{task.name} - {exception_name}\n')
        self.write(fail_info.get_msg())
        self.write("\n")


class TaskResult:
    """result object used by JsonReporter"""
    # FIXME what about returned value from python-actions ?
    def __init__(self, task):
        self.task = task
        self.result = None  # fail, success, up-to-date, ignore
        self.out = None  # stdout from task
        self.err = None  # stderr from task
        self.error = None  # error from doit (exception traceback)
        self.started = None  # datetime when task execution started
        self.elapsed = None  # time (in secs) taken to execute task
        self._started_on = None  # timestamp
        self._finished_on = None  # timestamp

    def start(self):
        """called when task starts its execution"""
        self._started_on = time.time()

    def set_result(self, result, error=None):
        """called when task finishes its execution"""
        self._finished_on = time.time()
        self.result = result
        line_sep = "\n<------------------------------------------------>\n"
        self.out = line_sep.join([a.out for a in self.task.actions if a.out])
        self.err = line_sep.join([a.err for a in self.task.actions if a.err])
        self.error = error

    def to_dict(self):
        """convert result data to dictionary"""
        if self._started_on is not None:
            started = datetime.datetime.fromtimestamp(
                self._started_on, datetime.timezone.utc)
            self.started = str(started.strftime('%Y-%m-%d %H:%M:%S.%f'))
            self.elapsed = self._finished_on - self._started_on
        return {'name': self.task.name,
                'result': self.result,
                'out': self.out,
                'err': self.err,
                'error': self.error,
                'started': self.started,
                'elapsed': self.elapsed}


class JsonReporter:
    """output results in JSON format

    - out (str)
    - err (str)
    - tasks (list - dict):
         - name (str)
         - result (str)
         - out (str)
         - err (str)
         - error (str)
         - started (str)
         - elapsed (float)
    """

    desc = 'output in JSON format'

    def __init__(self, outstream, options=None):  # pylint: disable=W0613
        # options parameter is not used
        # json result is sent to stdout when doit finishes running
        self.t_results = {}
        # when using json reporter output can not contain any other output
        # than the json data. so anything that is sent to stdout/err needs to
        # be captured.
        self._old_out = sys.stdout
        sys.stdout = StringIO()
        self._old_err = sys.stderr
        sys.stderr = StringIO()
        self.outstream = outstream
        # runtime and cleanup errors
        self.errors = []

    def get_status(self, task):
        """called when task is selected (check if up-to-date)"""
        self.t_results[task.name] = TaskResult(task)

    def execute_task(self, task):
        """called when execution starts"""
        self.t_results[task.name].start()

    def add_failure(self, task, exception):
        """called when execution finishes with a failure"""
        self.t_results[task.name].set_result('fail', exception.get_msg())

    def add_success(self, task):
        """called when execution finishes successfully"""
        self.t_results[task.name].set_result('success')

    def skip_uptodate(self, task):
        """skipped up-to-date task"""
        self.t_results[task.name].set_result('up-to-date')

    def skip_ignore(self, task):
        """skipped ignored task"""
        self.t_results[task.name].set_result('ignore')

    def cleanup_error(self, exception):
        """error during cleanup"""
        self.errors.append(exception.get_msg())

    def runtime_error(self, msg):
        """error from doit (not from a task execution)"""
        self.errors.append(msg)

    def teardown_task(self, task):
        """called when starts the execution of teardown action"""
        pass

    def complete_run(self):
        """called when finished running all tasks"""
        # restore stdout
        log_out = sys.stdout.getvalue()
        sys.stdout = self._old_out
        log_err = sys.stderr.getvalue()
        sys.stderr = self._old_err

        # add errors together with stderr output
        if self.errors:
            log_err += "\n".join(self.errors)

        task_result_list = [
            tr.to_dict() for tr in self.t_results.values()]
        json_data = {'tasks': task_result_list,
                     'out': log_out,
                     'err': log_err}
        # indent not available on simplejson 1.3 (debian etch)
        # json.dump(json_data, sys.stdout, indent=4)
        json.dump(json_data, self.outstream)


class _TqdmProxyStream:
    """File-like proxy for sys.stdout/sys.stderr that routes writes through
    tqdm.write() instead of a plain write(), so output interleaves cleanly
    above the bar instead of corrupting its carriage-return redraw.
    """

    def __init__(self, outstream, tqdm_cls):
        self._outstream = outstream
        self._buf = ""
        self._tqdm = tqdm_cls

    def write(self, text):
        self._buf += text
        *lines, self._buf = self._buf.split("\n")
        for line in lines:
            self._tqdm.write(line, file=self._outstream)
        return len(text)

    def flush(self):
        if self._buf:
            self._tqdm.write(self._buf, file=self._outstream)
            self._buf = ""
        if hasattr(self._outstream, "flush"):
            self._outstream.flush()

    def isatty(self):
        return hasattr(self._outstream, "isatty") and self._outstream.isatty()


class ProgressBarReporter(ConsoleReporter):
    """
    Progress bar reporter using the TQDM module.
    """

    desc = "progress bar (tqdm) instead of one line per task"

    def __init__(self, outstream, options):
        super().__init__(outstream, options)
        # Late import to make dependency optional
        from tqdm import tqdm

        self._tqdm = tqdm
        self.pbar = tqdm(total=0, unit="task", file=outstream, dynamic_ncols=True)
        # Route real-time task output through tqdm.write for the lifetime of
        # the run -- see _TqdmProxyStream for why this is what doit's task
        # execution actually picks up.
        self._old_stdout = sys.stdout
        self._old_stderr = sys.stderr
        sys.stdout = _TqdmProxyStream(outstream, tqdm)
        sys.stderr = _TqdmProxyStream(outstream, tqdm)

    @staticmethod
    def _is_tracked(task) -> bool:
        # Group/placeholder tasks (has_subtask, no actions of their own) and
        # private tasks (leading underscore, doit's own convention) aren't
        # real work -- counting them would swamp the bar with thousands of
        # zero-cost nodes.
        return bool(task.actions) and task.name[0] != '_'

    def initialize(self, tasks, selected_tasks):
        # Seed with every eagerly-loaded task already known before execution
        # starts. @create_after subtasks aren't among these yet -- their
        # loader placeholder has no actions, so _is_tracked already excludes
        # it -- those arrive later through update_total.
        self.pbar.total = sum(1 for t in tasks.values() if self._is_tracked(t))
        self.pbar.refresh()

    def update_total(self, new_tasks):
        n = sum(1 for t in new_tasks if self._is_tracked(t))
        if n:
            self.pbar.total += n
            self.pbar.refresh()

    def execute_task(self, task):
        if self._is_tracked(task):
            self.pbar.set_description(task.name[:60], refresh=False)

    def add_failure(self, task, fail):
        super().add_failure(task, fail)
        if self._is_tracked(task):
            self.pbar.update(1)

    def add_success(self, task):
        if self._is_tracked(task):
            self.pbar.update(1)

    def skip_uptodate(self, task):
        # Not real work -- shrink the total instead of advancing
        # progress, so a pipeline with many already-done tasks doesn't
        # report a fast rate/ETA from skips and then stall once it reaches
        # the actually-expensive remaining tasks.
        if self._is_tracked(task):
            self.pbar.total -= 1
            self.pbar.refresh()

    def skip_ignore(self, task):
        if self._is_tracked(task):
            self._tqdm.write("!! %s" % task.title(), file=self.outstream)
            self.pbar.total -= 1
            self.pbar.refresh()

    def _write_failure(self, result, write_exception=True):
        # Same content as ConsoleReporter._write_failure, but through
        # tqdm.write instead of self.write (plain outstream.write) so it
        # doesn't get mangled by the bar's own carriage-return redraw --
        # this fires immediately from add_failure, while the bar is still
        # active, not just from complete_run's after-the-fact replay.
        msg = '%s - taskid:%s' % (result['exception'].get_name(), result['task'].name)
        self._tqdm.write(msg, file=self.outstream)
        if write_exception:
            self._tqdm.write(result['exception'].get_msg(), file=self.outstream)

    def complete_run(self):
        self.pbar.refresh() # do a last refresh
        sys.stdout = self._old_stdout
        sys.stderr = self._old_stderr
        self.pbar.close()
        super().complete_run()