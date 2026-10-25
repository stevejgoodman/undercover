import { generatePath } from "react-router";

// The routes of the pages, and the links to the pages that show one thing.
export const QUEUE = "/";
export const CONFIGURATION = "/configuration";
export const SETTINGS = "/settings";
export const IMPROVEMENT = "/improvement";
export const SCOREBOARD = "/scoreboard";
export const CLAIM_PAGE = "/claims/:claimId";
export const EVALUATION_PAGE = `${SCOREBOARD}/:runId`;

export const claimPage = (claimId: string) =>
  generatePath(CLAIM_PAGE, { claimId });
export const evaluationPage = (runId: string) =>
  generatePath(EVALUATION_PAGE, { runId });
