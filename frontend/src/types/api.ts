// Mirrors backend/app/schemas. Will be generated from OpenAPI once the API surface grows.

export type Environment = "development" | "test" | "production";

export interface HealthResponse {
  status: "ok";
  app_name: string;
  version: string;
  environment: Environment;
  timestamp: string;
}
