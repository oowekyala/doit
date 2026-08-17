"""extra goodies to be used in dodo files"""

import glob
import os
import time as time_module
import datetime
import json
import hashlib
import operator
import subprocess

from . import exceptions
from .action import CmdAction, PythonAction
from .dependency import get_file_md5
from .task import result_dep  # imported for backward compatibility
result_dep  # pyflakes


class _Unset:
    """Marks a `task()` argument the caller did not pass.

    Not None, which several task attributes take as a meaningful value
    (`verbosity=None` means "use the default", and is not the same as leaving
    verbosity out).
    """
    def __repr__(self):
        return '<unset>'

_UNSET = _Unset()


def task(actions,
         name=_UNSET,
         basename=_UNSET,
         file_dep=_UNSET,
         task_dep=_UNSET,
         setup=_UNSET,
         targets=_UNSET,
         uptodate=_UNSET,
         calc_dep=_UNSET,
         getargs=_UNSET,
         teardown=_UNSET,
         doc=_UNSET,
         clean=_UNSET,
         params=_UNSET,
         pos_arg=_UNSET,
         verbosity=_UNSET,
         io=_UNSET,
         title=_UNSET,
         meta=_UNSET,
         watch=_UNSET,
         exclusive=_UNSET):
    """Build the dict a task-creator returns, with the fields spelled out.

    Exactly equivalent to writing the dict by hand -- this returns a plain
    dict and adds no behaviour -- but the field names are function arguments,
    so an editor completes them, a typo is a TypeError at load time instead of
    an InvalidTask later, and the documentation is where the task is written::

        def task_compile():
            for src in SOURCES:
                yield task(name=src.stem,
                           actions=[f'cc -c {src}'],
                           file_dep=[src],
                           targets=[src.with_suffix('.o')])

    Fields not passed are left out of the dict entirely, so `doit` applies its
    own defaults; the defaults named below are what it then uses.

    :param actions: what the task does. A list of:
        callable, or tuple (callable, `*args`, `**kwargs`) -- a python-action;
        string or list of strings -- a shell command;
        None for a group-task, which has no actions of its own.
    :param name: sub-task identifier. Required for a task yielded by a
        generator, and not used otherwise.
    :param basename: task name, instead of taking it from the name of the
        task-creator function.
    :param file_dep: (list of paths) files this task reads. The task is not up
        to date when any of them changed since it last ran.
    :param task_dep: (list of task names) tasks that must run before this one.
        An ordering, not a reason to re-run: a task_dep that executes does not
        by itself make this task out of date.
    :param setup: (list of task names) tasks to run first, but only if this
        task is going to execute. For preparing an environment this task needs
        and an up-to-date task does not.
    :param targets: (list of paths) files this task creates. A task whose
        targets are missing is not up to date, and `doit clean` removes them.
    :param uptodate: (list) each item None (ignored), a bool (False forces the
        task to run), or a callable taking (task, values) and returning
        bool or None.
    :param calc_dep: (list of task names) tasks whose result is a dict of
        further `file_dep` / `task_dep` / `uptodate` / `calc_dep` for this one.
        For dependencies too expensive to compute while loading tasks.
    :param getargs: (dict) name of a python-action argument -> tuple of
        (task name, variable name), passing another task's computed value in.
    :param teardown: (list of actions) run after every task has finished, in
        the reverse of the order their tasks executed.
    :param doc: (string) description, shown by `doit list`. Defaults to the
        task-creator's docstring.
    :param clean: True to remove the targets, or a list of actions to run, on
        `doit clean`.
    :param params: (list of dicts) command line options for this task's
        actions. Each names at least `name` and `default`, and may add
        `short`, `long`, `type`, `env_var`, `choices`, `help`, `inverse`.
    :param pos_arg: (string) name of the python-action argument that receives
        the task's positional command line arguments.
    :param verbosity: 0 capture stdout and stderr, 1 capture stdout only,
        2 capture nothing. None (default) to use the global setting.
    :param io: (dict) `{'capture': False}` to stop doit saving this task's
        output internally. Default `{'capture': True}`.
    :param title: (callable) takes the task and returns the line printed when
        it executes.
    :param meta: (dict) anything a custom command or plugin wants to read off
        the task. `doit` does not look at it.
    :param watch: (list of paths) extra paths for the `auto` command to watch,
        beyond `file_dep`. Folders are watched, but not their sub-folders.
    :param exclusive: True if this task must never run at the same time as
        another task. Only has an effect when running tasks in parallel.
        Default False.
    :return: (dict) the task, ready to be returned or yielded by a creator.
    """
    fields = {
        'actions': actions,
        'name': name,
        'basename': basename,
        'file_dep': file_dep,
        'task_dep': task_dep,
        'setup': setup,
        'targets': targets,
        'uptodate': uptodate,
        'calc_dep': calc_dep,
        'getargs': getargs,
        'teardown': teardown,
        'doc': doc,
        'clean': clean,
        'params': params,
        'pos_arg': pos_arg,
        'verbosity': verbosity,
        'io': io,
        'title': title,
        'meta': meta,
        'watch': watch,
        'exclusive': exclusive,
    }
    return {key: value for key, value in fields.items()
            if not isinstance(value, _Unset)}


# action
def create_folder(dir_path):
    """create a folder in the given path if it doesnt exist yet."""
    os.makedirs(dir_path, exist_ok=True)


# title
def title_with_actions(task):
    """return task name task actions"""
    if task.actions:
        title = "\n\t".join([str(action) for action in task.actions])
    # A task that contains no actions at all
    # is used as group task
    else:
        title = "Group: %s" % ", ".join(task.task_dep)
    return "%s => %s" % (task.name, title)



# uptodate
def run_once(task, values):
    """execute task just once
    used when user manually manages a dependency
    """
    def save_executed():
        return {'run-once': True}
    task.value_savers.append(save_executed)
    return values.get('run-once', False)



# uptodate
class config_changed:
    """check if passed config was modified
    @var config (str) or (dict)
    @var encoder (json.JSONEncoder) Encoder used to convert non-default values.
    """
    def __init__(self, config, encoder=None):
        self.config = config
        self.config_digest = None
        self.encoder = encoder

    def _calc_digest(self):
        if isinstance(self.config, str):
            return self.config
        elif isinstance(self.config, dict):
            data = json.dumps(self.config, sort_keys=True, cls=self.encoder)
            byte_data = data.encode("utf-8")
            return hashlib.md5(byte_data).hexdigest()
        else:
            msg = ('Invalid type of config_changed parameter got %s,'
                   ' must be string or dict')
            raise Exception(msg % (type(self.config),))

    def configure_task(self, task):
        task.value_savers.append(lambda: {'_config_changed': self.config_digest})

    def __call__(self, task, values):
        """return True if config values are UNCHANGED"""
        self.config_digest = self._calc_digest()
        last_success = values.get('_config_changed')
        if last_success is None:
            return False
        return (last_success == self.config_digest)

    def __repr__(self):
        return "config_changed(%r)" % self.config



# uptodate
class glob_dep:
    """check if the set of files matched by a glob pattern, or the content
    of any matched file, changed since last run.

    Unlike file_dep (a fixed list of paths known up front when the task is
    created), this is for tasks whose dependency set is only known by
    scanning the filesystem -- e.g. "every csv currently under some
    directory" -- where the match set itself, not just each matched file's
    content, can change between runs (files appearing/disappearing should
    also mark the task as not up to date, not just files being edited).

    Per-file state is (mtime, size, md5) -- the same (timestamp, file-size,
    md5) shortcut MD5Checker uses (see its docstring): md5 is only
    recomputed for a file whose mtime doesn't match what's on record, so an
    unchanged file is never re-hashed on subsequent checks, only ones that
    are new or whose mtime moved. A file touched without its content
    actually changing (new mtime, same md5) still compares as unchanged --
    only the md5 is compared, not the whole state tuple -- so it doesn't
    force a rerun either.

    @var pattern (str): glob pattern, passed to glob.glob()
    @var recursive (bool): passed through to glob.glob() (enables "**")
    """
    def __init__(self, pattern, recursive=False):
        self.pattern = pattern
        self.recursive = recursive
        self.state = None
        self.key = '_glob_dep:%s' % pattern

    def _calc_state(self, matched, previous):
        previous = previous or {}
        state = {}
        for path in matched:
            file_stat = os.stat(path)
            prev_entry = previous.get(path)
            if prev_entry and prev_entry[0] == file_stat.st_mtime:
                state[path] = prev_entry  # mtime unchanged, skip re-hashing
            else:
                state[path] = (file_stat.st_mtime, file_stat.st_size,
                                get_file_md5(path))
        return state

    def configure_task(self, task):
        task.value_savers.append(lambda: {self.key: self.state})

    def __call__(self, task, values):
        """return True if the matched file set is unchanged and every
        matched file's content (md5, not mtime/size) matches last run"""
        matched = sorted(p for p in glob.glob(self.pattern, recursive=self.recursive)
                          if os.path.isfile(p))
        previous = values.get(self.key)
        self.state = self._calc_state(matched, previous)
        if previous is None:
            return False
        if set(previous) != set(matched):
            return False
        return all(previous[path][2] == self.state[path][2] for path in matched)

    def __repr__(self):
        return "glob_dep(%r)" % self.pattern



# uptodate
class timeout:
    """add timeout to task

    @param timeout_limit: (datetime.timedelta, int) in seconds

    if the time elapsed since last time task was executed is bigger than
    the "timeout" time the task is NOT up-to-date
    """

    def __init__(self, timeout_limit):
        if isinstance(timeout_limit, datetime.timedelta):
            self.limit_sec = ((timeout_limit.days * 24 * 3600)
                              + timeout_limit.seconds)
        elif isinstance(timeout_limit, int):
            self.limit_sec = timeout_limit
        else:
            msg = "timeout should be datetime.timedelta or int got %r "
            raise Exception(msg % timeout_limit)

    def __call__(self, task, values):
        def save_now():
            return {'success-time': time_module.time()}
        task.value_savers.append(save_now)
        last_success = values.get('success-time', None)
        if last_success is None:
            return False
        return (time_module.time() - last_success) < self.limit_sec



# uptodate
class check_timestamp_unchanged:
    """check if timestamp of a given file/dir is unchanged since last run.

    The C{cmp_op} parameter can be used to customize when timestamps are
    considered unchanged, e.g. you could pass L{operator.ge} to also consider
    e.g. files reverted to an older copy as unchanged; or pass a custom
    function to completely customize what unchanged means.

    If the specified file does not exist, an exception will be raised.  Note
    that if the file C{fn} is a target of another task you should probably add
    C{task_dep} on that task to ensure the file is created before checking it.
    """
    def __init__(self, file_name, time='mtime', cmp_op=operator.eq):
        """initialize the callable

        @param fn: (str) path to file/directory to check
        @param time: (str) which timestamp field to check, can be one of
                     (atime, access, ctime, status, mtime, modify)
        @param cmp_op: (callable) takes two parameters (prev_time, current_time)
                   should return True if the timestamp is considered unchanged

        @raises ValueError: if invalid C{time} value is passed
        """
        if time in ('atime', 'access'):
            self._timeattr = 'st_atime'
        elif time in ('ctime', 'status'):
            self._timeattr = 'st_ctime'
        elif time in ('mtime', 'modify'):
            self._timeattr = 'st_mtime'
        else:
            raise ValueError('time can be one of: atime, access, ctime, '
                             'status, mtime, modify (got: %r)' % time)
        self._file_name = str(file_name)
        self._cmp_op = cmp_op
        self._key = '.'.join([self._file_name, self._timeattr])

    def _get_time(self):
        return getattr(os.stat(self._file_name), self._timeattr)

    def __call__(self, task, values):
        """register action that saves the timestamp and check current timestamp

        @raises OSError: if cannot stat C{self._file_name} file
                         (e.g. doesn't exist)
        """
        def save_now():
            return {self._key: self._get_time()}
        task.value_savers.append(save_now)

        prev_time = values.get(self._key)
        if prev_time is None:  # this is first run
            return False
        current_time = self._get_time()
        return self._cmp_op(prev_time, current_time)


# action class
class LongRunning(CmdAction):
    """Action to handle a Long running shell process,
    usually a server or service.
    Properties:

        * the output is never captured
        * it is always successful (return code is not used)
        * "swallow" KeyboardInterrupt
    """
    def execute(self, out=None, err=None):
        action = self.expand_action()
        process = subprocess.Popen(
            action, shell=self.shell, stdout=out, stderr=err, **self.pkwargs)
        try:
            process.wait()
        except KeyboardInterrupt:
            # normal way to stop interactive process
            pass

# the name InteractiveAction is deprecated on 0.25
InteractiveAction = LongRunning


class Interactive(CmdAction):
    """Action to handle Interactive shell process:

       * the output is never captured
    """
    def execute(self, out=None, err=None):
        action = self.expand_action()
        process = subprocess.Popen(
            action, shell=self.shell, stdout=out, stderr=err, **self.pkwargs)
        process.wait()
        if process.returncode != 0:
            return exceptions.TaskFailed(
                "Interactive command failed: '%s' returned %s" %
                (action, process.returncode))



# action class
class PythonInteractiveAction(PythonAction):
    """Action to handle Interactive python:

       * the output is never captured
       * it is successful unless a exception is raised
    """
    def execute(self, out=None, err=None):
        kwargs = self._prepare_kwargs()
        try:
            returned_value = self.py_callable(*self.args, **kwargs)
        except Exception as exception:
            return exceptions.TaskError("PythonAction Error", exception)
        if isinstance(returned_value, str):
            self.result = returned_value
        elif isinstance(returned_value, dict):
            self.values = returned_value
            self.result = returned_value


# debug helper
def set_trace():  # pragma: no cover
    """start debugger, make sure stdout shows pdb output.
    output is not restored.
    """
    import pdb
    import sys
    debugger = pdb.Pdb(stdin=sys.__stdin__, stdout=sys.__stdout__)
    debugger.set_trace(sys._getframe().f_back)  # pylint: disable=W0212



def load_ipython_extension(ip=None):  # pragma: no cover
    """
    Defines a ``%doit`` magic function[1] that discovers and execute tasks
    from IPython's interactive variables (global namespace).

    It will fail if not invoked from within an interactive IPython shell.

    .. Tip::
        To permanently add this magic-function to your IPython, create a new
        script inside your startup-profile
        (``~/.ipython/profile_default/startup/doit_magic.ipy``) with the
        following content:

            %load_ext doit
            %reload_ext doit
            %doit list

    [1] http://ipython.org/ipython-doc/dev/interactive/tutorial.html#magic-functions
    """
    from IPython.core.getipython import get_ipython
    from IPython.core.magic import register_line_magic

    from doit.cmd_base import ModuleTaskLoader
    from doit.doit_cmd import DoitMain

    # Only (re)load_ext provides the ip context.
    ip = ip or get_ipython()

    @register_line_magic
    def doit(line):
        """
        Run *doit* with `task_creators` from all interactive variables
        (IPython's global namespace).

        Examples:

            >>> %doit --help          ## Show help for options and arguments.

            >>> def task_foo():
                    return {'actions': ['echo hi IPython'],
                            'verbosity': 2}

            >>> %doit list            ## List any tasks discovered.
            foo

            >>> %doit                 ## Run any tasks.
            .  foo
            hi IPython

        """
        # Override db-files location inside ipython-profile dir,
        # which is certainly writable.
        prof_dir = ip.profile_dir.location
        opt_vals = {'dep_file': os.path.join(prof_dir, 'db', '.doit.db')}
        commander = DoitMain(ModuleTaskLoader(ip.user_module),
                             extra_config={'GLOBAL': opt_vals})
        commander.BIN_NAME = 'doit'
        commander.run(line.split())

# also expose another way of registering ipython extension
register_doit_as_IPython_magic = load_ipython_extension
