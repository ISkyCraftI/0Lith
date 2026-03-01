export type AgentId =
  | "hodolith"
  | "monolith"
  | "aerolith"
  | "cryolith"
  | "pyrolith";
export type AgentStatus = "idle" | "thinking" | "responding" | "offline";
export type MessageType = "user" | "agent" | "routing" | "system" | "error";

export interface ChatMessage {
  id: string;
  type: MessageType;
  content: string;
  agentId?: AgentId;
  agentName?: string;
  agentColor?: string;
  agentEmoji?: string;
  timestamp: number;
  responseTime?: number; // seconds
  rating?: "up" | "down" | null;
  ratingReason?: string;
}

export interface Agent {
  id: AgentId;
  name: string;
  role: string;
  model: string;
  color: string;
  emoji: string;
  description: string;
  capabilities: string[];
  location: "local" | "docker";
}

export interface IPCRequest {
  id: string;
  command:
    | "status"
    | "chat"
    | "search"
    | "memory_init"
    | "agents_list"
    | "gaming_mode"
    | "set_project_root"
    | "read_file"
    | "list_files"
    | "search_files"
    | "clear_history"
    | "feedback"
    | "system_info"
    | "clear_memories"
    | "list_sessions"
    | "load_session"
    | "new_session"
    | "cancel"
    | "arena";
  [key: string]: unknown;
}

export interface IPCResponse {
  id: string;
  status: "ok" | "error" | "streaming" | "routing" | "arena";
  message?: string;
  chunk?: string;
  [key: string]: unknown;
}

export interface LoadedModel {
  name: string;
  size_gb: number;
  vram_gb: number;
}

export interface StatusResponse extends IPCResponse {
  ollama: boolean;
  qdrant: boolean;
  pyrolith_docker: boolean;
  memory_initialized: boolean;
  models: Record<string, boolean>;
  loaded_models?: LoadedModel[];
  vram_used_gb?: number;
  gaming_mode?: boolean;
}

export interface AgentsListResponse extends IPCResponse {
  agents: Agent[];
}

export interface ChatResponse extends IPCResponse {
  agent_id: AgentId;
  agent_name: string;
  agent_color: string;
  agent_emoji: string;
  response: string;
  model: string;
  memories_used: number;
  route_reason?: string;
  tool_iterations?: number;
}

export interface SearchResponse extends IPCResponse {
  results: Array<{
    text: string;
    score?: number;
    metadata?: Record<string, unknown>;
  }>;
  agent_id: string;
  query: string;
}

export interface MemoryInitResponse extends IPCResponse {
  agents_registered: number;
  relations_registered: boolean;
  sparring_protocol: boolean;
  graph_enabled: boolean;
}

export interface GamingModeResponse extends IPCResponse {
  gaming_mode: boolean;
  models_unloaded: number;
}

// ── Watcher Events (olith_watcher.py — push-based, not request-response) ──

export type WatcherEventType = "file_change" | "schedule" | "shadow";

export interface WatcherEvent {
  event: "suggestion";
  type: WatcherEventType;
  id: string;
  text: string;
  context: {
    files?: string[];
    diff_summary?: string;
    schedule_slot?: string;
    shadow_query?: string;
  };
  timestamp: number;
}

export interface WatcherCommand {
  command: "pause" | "resume" | "set_watch_dir" | "feedback";
  suggestion_id?: string;
  action?: "accepted" | "dismissed" | "modified";
  modified_text?: string;
  watch_dir?: string;
}

// ── Session History ──

export interface SessionInfo {
  session_id: string;
  message_count: number;
  preview: string;
  updated_at: number;
}

export interface ListSessionsResponse extends IPCResponse {
  sessions: SessionInfo[];
}

export interface LoadSessionResponse extends IPCResponse {
  session_id: string;
  messages: ChatMessage[];
}

export interface NewSessionResponse extends IPCResponse {
  session_id: string;
}

export interface WatcherStatusEvent {
  event: "status";
  watching: boolean;
  watch_dir: string;
  paused: boolean;
  ollama_available: boolean;
}

// ── Arena ──

export interface ArenaMove {
  team: "red" | "blue";
  type: string; // RECON | EXPLOIT | SUCCESS | PIVOT | DATA | MONITOR | ALERT | BLOCK | PATCH | ISOLATE
  message: string;
  timestamp: string; // "HH:MM:SS"
  badge_color: string;
  duration_s?: number; // LLM response time in seconds
  details?: string;    // technical payload / additional context
}

export interface ArenaScore {
  red: number;
  blue: number;
}

export interface ArenaEvent extends IPCResponse {
  // status: "arena"
  phase?: "start" | "review_start" | "complete";
  move?: ArenaMove;
  score?: ArenaScore;
  scenario?: string;
  review?: { red: string; blue: string };
}

export interface ArenaResponse extends IPCResponse {
  // status: "ok" — final response after all rounds
  score_red: number;
  score_blue: number;
  review: { red: string; blue: string };
}
