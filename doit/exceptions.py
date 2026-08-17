"""Handle exceptions generated from 'user' code"""

import difflib
import sys
import traceback


# how many alternatives to offer, and how similar a name must be to be
# worth offering (difflib similarity ratio, 0..1)
SUGGEST_MAX = 3
SUGGEST_CUTOFF = 0.6


def did_you_mean(name, candidates):
    """suggest a correction for a misspelled `name`

    @param candidates: (iterable - str) the valid names
    @return (str) a 'Did you mean' sentence, or '' if nothing is close enough
    """
    if not name or not candidates:
        return ''
    # a name can legitimately be in the pool twice (a task named after its
    # own target, say) and would then take up two of the slots
    unique = list(dict.fromkeys(candidates))
    close = difflib.get_close_matches(name, unique,
                                      n=SUGGEST_MAX, cutoff=SUGGEST_CUTOFF)
    if not close:
        return ''
    return 'Did you mean: {}?'.format(', '.join(close))


class InvalidCommand(Exception):
    """Invalid command line argument."""

    def __init__(self, *args, **kwargs):
        self.not_found = kwargs.pop('not_found', None)
        # valid names `not_found` might be a misspelling of
        self.candidates = list(kwargs.pop('candidates', ()))
        super(InvalidCommand, self).__init__(*args, **kwargs)
        self.cmd_used = None
        self.bin_name = 'doit'  # default but might be overwriten

    def add_candidates(self, names):
        """add names to the pool used to suggest a correction

        Used by callers that know about valid names the raising code did
        not, i.e. the sub-command names when no command was specified.
        """
        self.candidates.extend(names)

    def __str__(self):
        if self.not_found is None:
            return super(InvalidCommand, self).__str__()

        suggestion = did_you_mean(self.not_found, self.candidates)
        did_you_mean_line = suggestion + '\n' if suggestion else ''

        if self.cmd_used:
            msg_task_not_found = (
                'command `{cmd_used}` invalid parameter: "{not_found}".'
                ' Must be a task, or a target.\n'
                '{did_you_mean}'
                'Type "{bin_name} list" to see available tasks')
        else:
            msg_task_not_found = (
                'Invalid parameter: "{not_found}".'
                ' Must be a command, task, or a target.\n'
                '{did_you_mean}'
                'Type "{bin_name} help" to see available commands.\n'
                'Type "{bin_name} list" to see available tasks.\n')
        return msg_task_not_found.format(did_you_mean=did_you_mean_line,
                                         **self.__dict__)




class InvalidDodoFile(Exception):
    """Invalid dodo file"""
    pass

class InvalidTask(Exception):
    """Invalid task instance. User error on specifying the task."""
    pass



class CatchedException():
    """DEPRECATED, use BaseFail instead. 2022-04-22 0.36.0 release.

    Wrong grammar and not all BaseFail contains an Exception

    :ivar report: used by (some) reporters to decide if Failure/Error should be in printed
    """
    def __init__(self, msg, exception=None, report=True):
        self.message = msg
        self.traceback = ''
        self.report = report
        # It would be nice to include original exception, but they are not always pickable
        # https://stackoverflow.com/questions/49715881/how-to-pickle-inherited-exceptions

        if isinstance(exception, BaseFail):
            self.traceback = exception.traceback
        elif exception is not None:
            self.traceback = traceback.format_exception(
                exception.__class__, exception, sys.exc_info()[2])

    def get_msg(self):
        """return full exception description (includes traceback)"""
        return "%s\n%s" % (self.message, "".join(self.traceback))

    def get_name(self):
        """get fail kind name"""
        return self.__class__.__name__

    def __repr__(self):
        return "(<%s> %s)" % (self.get_name(), self.message)

    def __str__(self):
        return "%s\n%s" % (self.get_name(), self.get_msg())


class BaseFail(CatchedException):
    """This used to save info Task failures/errors

    Might contain a caught Exception.
    """
    pass

class TaskFailed(BaseFail):
    """Task execution was not successful."""
    pass


class TaskError(BaseFail):
    """Error while trying to execute task."""
    pass


class UnmetDependency(TaskError):
    """Task was not executed because a dependent task failed or is ignored"""
    pass


class SetupError(TaskError):
    """Error while trying to execute setup object"""
    pass


class DependencyError(TaskError):
    """Error while trying to check if task is up-to-date or saving task status"""
    pass
