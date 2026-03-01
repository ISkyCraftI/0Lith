import type { Agent, AgentId, AgentStatus } from '../../types/ipc';

let agents = $state<Agent[]>([]);
let statuses = $state<Record<string, AgentStatus>>({
  hodolith: 'idle',
  monolith: 'idle',
  aerolith: 'idle',
  cryolith: 'idle',
  pyrolith: 'offline',
});

export function getAgents(): Agent[] {
  return agents;
}

export function setAgents(list: Agent[]): void {
  agents = list;
}

export function getStatus(id: AgentId): AgentStatus {
  return statuses[id] ?? 'offline';
}

export function setStatus(id: AgentId, status: AgentStatus): void {
  statuses = { ...statuses, [id]: status };
}

export function getAllStatuses(): Record<string, AgentStatus> {
  return statuses;
}
