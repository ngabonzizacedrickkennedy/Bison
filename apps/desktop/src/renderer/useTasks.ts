import { useCallback, useEffect, useState } from "react";
import {
  createTask,
  fetchProgress,
  fetchTasks,
  moveTask,
  type ProgressSnapshot,
  type Task,
  type TaskDraft,
} from "./tasks";

export type TasksState = "loading" | "ready" | "failed";

export interface TasksView {
  tasksState: TasksState;
  tasks: Task[];
  progress: ProgressSnapshot | null;
  refresh: () => Promise<void>;
  addTask: (draft: TaskDraft) => Promise<void>;
  transition: (taskId: string, state: string, reason: string | null) => Promise<void>;
}

export function useTasks(httpUrl: string): TasksView {
  const [tasksState, setTasksState] = useState<TasksState>("loading");
  const [tasks, setTasks] = useState<Task[]>([]);
  const [progress, setProgress] = useState<ProgressSnapshot | null>(null);

  const load = useCallback(async (): Promise<[Task[], ProgressSnapshot | null]> => {
    return Promise.all([fetchTasks(httpUrl), fetchProgress(httpUrl)]);
  }, [httpUrl]);

  useEffect(() => {
    let cancelled = false;

    load()
      .then(([loadedTasks, loadedProgress]) => {
        if (cancelled) {
          return;
        }
        setTasks(loadedTasks);
        setProgress(loadedProgress);
        setTasksState("ready");
      })
      .catch(() => {
        if (!cancelled) {
          setTasksState("failed");
        }
      });

    return () => {
      cancelled = true;
    };
  }, [load]);

  const refresh = useCallback(async () => {
    const [loadedTasks, loadedProgress] = await load();
    setTasks(loadedTasks);
    setProgress(loadedProgress);
    setTasksState("ready");
  }, [load]);

  const addTask = useCallback(
    async (draft: TaskDraft) => {
      await createTask(httpUrl, draft);
      await refresh();
    },
    [httpUrl, refresh],
  );

  const transition = useCallback(
    async (taskId: string, state: string, reason: string | null) => {
      await moveTask(httpUrl, taskId, { state, reason });
      await refresh();
    },
    [httpUrl, refresh],
  );

  return { tasksState, tasks, progress, refresh, addTask, transition };
}
