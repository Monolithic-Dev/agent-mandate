import { useCallback } from "react";
import { useNavigate } from "react-router-dom";

import type { GraphElement } from "./types";

/** Where a graph element leads: decisions and instructions have their own pages. */
export function useElementLinks(tenantId: string) {
  const navigate = useNavigate();
  return useCallback(
    (element: GraphElement) => {
      if (element.data.label === "Decision") {
        navigate(`/tenants/${tenantId}/decisions/${element.data.id}`);
      } else if (element.data.label === "Instruction") {
        navigate(`/tenants/${tenantId}/instructions/${element.data.id}`);
      }
    },
    [navigate, tenantId],
  );
}
