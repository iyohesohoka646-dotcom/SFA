import { createContext, useContext, type ReactNode } from "react";
import { createResearchClient } from "../client";
import { createWorkbenchClient } from "./WorkbenchClient";

export function createResearchServices(projectId?: string) {
  const apiPrefix =
    "/api/v1/research" +
    (projectId ? "/projects/" + encodeURIComponent(projectId) : "");
  const research = createResearchClient(apiPrefix);
  return {
    projectId,
    apiPrefix,
    research,
    workbench: createWorkbenchClient(research.request, apiPrefix),
  };
}
export type ResearchServices = ReturnType<typeof createResearchServices>;
const legacy = createResearchServices();
const Services = createContext<ResearchServices>(legacy);
export function ResearchServicesProvider({
  services,
  children,
}: {
  services: ResearchServices;
  children: ReactNode;
}) {
  return <Services.Provider value={services}>{children}</Services.Provider>;
}
export const useResearchServices = () => useContext(Services);
export const useResearchClient = () => useResearchServices().research.client;
export const useWorkbenchClient = () => useResearchServices().workbench;
