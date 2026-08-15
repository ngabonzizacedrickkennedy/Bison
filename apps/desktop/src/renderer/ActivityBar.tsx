import type { Activity } from "./activity";

interface ActivityBarProps {
  activity: Activity;
  elapsedSeconds: number;
}

export function ActivityBar({ activity, elapsedSeconds }: ActivityBarProps) {
  if (activity.phase === "idle") {
    return null;
  }

  if (activity.phase === "invoking") {
    return (
      <div className="activity thinking">
        <span className="pulse" />
        <span className="label">
          {activity.role} thinking on {activity.modelId}
        </span>
        <span className="locality">{activity.locality}</span>
        <span className="elapsed">{elapsedSeconds}s</span>
      </div>
    );
  }

  if (activity.phase === "answered") {
    return (
      <div className="activity answered">
        <span className="label">
          {activity.modelId} answered in {(activity.latencyMs / 1000).toFixed(1)}s
        </span>
        {activity.failedOverFrom !== null && (
          <span className="locality">failed over from {activity.failedOverFrom}</span>
        )}
      </div>
    );
  }

  return (
    <div className="activity failed">
      <span className="label">{activity.reason}</span>
    </div>
  );
}
