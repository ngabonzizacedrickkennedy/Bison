import type { Project } from "@bison/contracts";
import { broadcast, readState, type HaltSignal, type HaltStateReport } from "./halt.js";
import {
  activateProject,
  listProjects,
  readProject,
  type ProjectTransition,
} from "./project-client.js";

export interface SwitchOutcome {
  switched: boolean;
  activated: Project;
  paused: string | null;
  signal: HaltSignal | null;
  halt: HaltStateReport;
}

export class SwitchRefusedError extends Error {
  constructor(
    readonly projectId: string,
    readonly state: string,
  ) {
    super(`project ${projectId} is ${state} and cannot be activated`);
    this.name = "SwitchRefusedError";
  }
}

async function incumbentProject(): Promise<Project | null> {
  const listed = await listProjects("active");

  return listed.projects[0] ?? null;
}

async function haltIncumbent(incumbent: Project | null): Promise<HaltSignal | null> {
  if (incumbent === null) {
    return null;
  }

  return broadcast({
    reason: "project_switch",
    requestId: null,
    projectId: incumbent.id,
    taskId: null,
  });
}

export async function switchProject(
  projectId: string,
  transition: ProjectTransition,
): Promise<SwitchOutcome> {
  const target = await readProject(projectId);

  if (target.state === "archived") {
    throw new SwitchRefusedError(target.id, target.state);
  }

  const incumbent = await incumbentProject();

  if (incumbent !== null && incumbent.id === target.id) {
    return {
      switched: false,
      activated: incumbent,
      paused: null,
      signal: null,
      halt: await readState(),
    };
  }

  const signal = await haltIncumbent(incumbent);
  const activated = await activateProject(target.id, transition);

  return {
    switched: true,
    activated,
    paused: incumbent === null ? null : incumbent.id,
    signal,
    halt: await readState(),
  };
}
