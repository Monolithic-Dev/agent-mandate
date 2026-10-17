import "@testing-library/jest-dom/vitest";

import { configure } from "@testing-library/react";

// jsdom is slow to start on a loaded machine (CI, or every file at once): give the findBy
// queries room, so a slow run is not mistaken for a broken one.
configure({ asyncUtilTimeout: 4000 });
