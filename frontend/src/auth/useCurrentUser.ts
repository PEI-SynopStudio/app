import { useRouteLoaderData } from "react-router";
import type { User } from "../lib/auth";
import { AUTH_ROUTE_ID, type requireUser } from "./loaders";

/** The signed-in user, inside the routes that requireUser guards. */
export function useCurrentUser(): User {
  const user = useRouteLoaderData<typeof requireUser>(AUTH_ROUTE_ID);
  if (!user) throw new Error("useCurrentUser is used outside the signed-in routes.");
  return user;
}
