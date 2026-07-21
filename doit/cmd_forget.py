from .cmd_base import DoitCmdBase, check_tasks_exist
from .cmd_base import tasks_and_deps_iter, subtasks_iter


opt_forget_taskdep = {
    'name': 'forget_sub',
    'short': 's',
    'long': 'follow-sub',
    'type': bool,
    'default': False,
    'help': 'forget task dependencies too',
}

opt_disable_default = {
    'name': 'forget_disable_default',
    'long': 'disable-default',
    'inverse': 'enable-default',
    'type': bool,
    'default': False,
    'help': 'disable forgetting default tasks (when no arguments are passed)',
}

opt_forget_all = {
    'name': 'forget_all',
    'short': 'a',
    'long': 'all',
    'type': bool,
    'default': False,
    'help': 'forget all tasks',
}



class Forget(DoitCmdBase):
    doc_purpose = "clear successful run status from internal DB"
    doc_usage = "[TASK ...]"
    doc_description = None

    cmd_options = (opt_forget_taskdep, opt_disable_default, opt_forget_all)

    def _execute(self, forget_sub, forget_disable_default, forget_all):
        """remove saved data successful runs from DB
        """
        if forget_all:
            self.dep_manager.remove_all()
            self.outstream.write("forgetting all tasks\n")

        elif self.sel_default_tasks and forget_disable_default:
            self.outstream.write(
                "no tasks specified, pass task name, --enable-default or --all\n")

        # forget tasks from list
        else:
            tasks = dict([(t.name, t) for t in self.task_list])
            check_tasks_exist(tasks, self.sel_tasks)
            forget_list = self.sel_tasks

            # always forget the selected tasks together with their
            # structural subtasks (task-group members), never their deps
            to_forget = []
            seen = set()
            for name in forget_list:
                task = tasks[name]
                for sub in [task] + list(subtasks_iter(tasks, task)):
                    if sub.name not in seen:
                        seen.add(sub.name)
                        to_forget.append(sub)

            if forget_sub:
                # additionally forget the (real) dependencies of every
                # task/subtask found above
                for dep in tasks_and_deps_iter(tasks, [t.name for t in to_forget]):
                    if dep.name not in seen:
                        seen.add(dep.name)
                        to_forget.append(dep)

            for task in to_forget:
                # forget it - remove from dependency file
                self.dep_manager.remove(task.name)
                self.outstream.write("forgetting %s\n" % task.name)
        self.dep_manager.close()
