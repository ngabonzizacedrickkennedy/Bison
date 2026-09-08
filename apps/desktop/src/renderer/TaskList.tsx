import type { ProgressSnapshot, Task } from "./tasks";
import type { TasksState } from "./useTasks";

interface TaskListProps {
  tasksState: TasksState;
  tasks: Task[];
  progress: ProgressSnapshot | null;
  onTransition: (taskId: string, state: string, reason: string | null) => void;
}

const SETTLED = new Set(["completed", "skipped", "ignored", "failed"]);

function depthOf(task: Task, byId: Map<string, Task>): number {
  let depth = 0;
  let parentId = task.parent_id;
  const seen = new Set<string>([task.id]);

  while (parentId !== null && !seen.has(parentId)) {
    const parent = byId.get(parentId);
    if (parent === undefined) {
      break;
    }
    seen.add(parentId);
    parentId = parent.parent_id;
    depth += 1;
  }

  return depth;
}

export function TaskList({ tasksState, tasks, progress, onTransition }: TaskListProps) {
  if (tasksState === "loading") {
    return <div className="tasks">loading the task tree</div>;
  }

  if (tasksState === "failed") {
    return <div className="tasks">task tree unavailable — project-service is not running</div>;
  }

  if (tasks.length === 0) {
    return <div className="tasks">no tasks yet</div>;
  }

  const byId = new Map(tasks.map((task) => [task.id, task]));
  const ordered = [...tasks].sort((left, right) => left.position - right.position);
  const percentageFor = (taskId: string): number | null =>
    progress?.per_task.find((entry) => entry.task_id === taskId)?.percentage ?? null;

  return (
    <div className="tasks">
      <div className="tasks-head">
        <span className="tasks-title">task tree</span>
        <span className="tasks-overall">
          {progress === null ? "progress unavailable" : `${progress.overall.percentage}% overall`}
        </span>
      </div>

      {ordered.map((task) => {
        const percentage = percentageFor(task.id);
        const restorable = task.state === "skipped" || task.state === "ignored";

        return (
          <div
            className={`task ${task.state}`}
            key={task.id}
            style={{ marginLeft: `${depthOf(task, byId) * 16}px` }}
          >
            <span className="task-title" title={task.description}>
              {task.title}
            </span>
            <span className="task-state">{task.state.replace("_", " ")}</span>
            <span className="task-percentage">{percentage === null ? "—" : `${percentage}%`}</span>

            <span className="task-controls">
              {restorable ? (
                <button type="button" onClick={() => onTransition(task.id, "pending", null)}>
                  Restore
                </button>
              ) : (
                <>
                  <button
                    type="button"
                    disabled={SETTLED.has(task.state)}
                    onClick={() => onTransition(task.id, "skipped", "skipped by user")}
                  >
                    Skip
                  </button>
                  <button
                    type="button"
                    disabled={SETTLED.has(task.state)}
                    onClick={() => onTransition(task.id, "ignored", "ignored by user")}
                  >
                    Ignore
                  </button>
                </>
              )}
            </span>
          </div>
        );
      })}
    </div>
  );
}
