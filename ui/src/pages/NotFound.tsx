import { Compass } from "../icons";
import { Link } from "react-router-dom";

import { EmptyState } from "../components/ui";

export function NotFound() {
  return (
    <div className="page">
      <EmptyState icon={Compass} title="No such page.">
        <Link to="/">Back to the demo</Link>
      </EmptyState>
    </div>
  );
}
