/* Generated from Python model profiles; scripts/export_schema.py + npm run types. */

export type Id = string;
export type Protocol = "offline" | "openai-compatible" | "anthropic";
export type BaseUrl = string;
/**
 * @maxItems 2000
 */
export type Models = string[];
export type DefaultModel = string;
export type TimeoutSeconds = number;
export type CredentialRef = string | null;
export type Id1 = string;
export type Protocol1 = "offline" | "openai-compatible" | "anthropic";
export type BaseUrl1 = string;
/**
 * @maxItems 2000
 */
export type Models1 = string[];
export type DefaultModel1 = string;
export type TimeoutSeconds1 = number;
export type CredentialRef1 = string | null;
export type Configured = boolean;
export type Status = "connected" | "error" | "cancelled" | "offline";
export type OperationId = string;
export type Message = string;
export type Models2 = string[];
export type Inference = boolean;
export type DurationMs = number;
export type Requests = number;

export interface ModelsProtocol {
  ProviderProfile: ProviderProfile;
  PublicProviderProfile: PublicProviderProfile;
  ConnectionResult: ConnectionResult;
}
export interface ProviderProfile {
  id: Id;
  protocol: Protocol;
  base_url: BaseUrl;
  models: Models;
  default_model: DefaultModel;
  timeout_seconds: TimeoutSeconds;
  credential_ref: CredentialRef;
}
export interface PublicProviderProfile {
  id: Id1;
  protocol: Protocol1;
  base_url: BaseUrl1;
  models: Models1;
  default_model: DefaultModel1;
  timeout_seconds: TimeoutSeconds1;
  credential_ref: CredentialRef1;
  configured: Configured;
}
export interface ConnectionResult {
  status: Status;
  operation_id: OperationId;
  message: Message;
  models: Models2;
  inference: Inference;
  usage: Usage;
  duration_ms: DurationMs;
  requests: Requests;
}
export interface Usage {
  [k: string]: number;
}
