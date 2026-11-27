import { createBrowserRouter } from "react-router";
import { AUTH_ROUTE_ID, redirectIfSignedIn, requireUser } from "./auth/loaders";
import { SessionError, SessionPending } from "./auth/SessionStatus";
import { AppLayout } from "./layouts/AppLayout";
import { RootLayout } from "./layouts/RootLayout";
import { ClipEditor } from "./pages/app/ClipEditor";
import { ClipDetail } from "./pages/app/ClipDetail";
import { NewProject } from "./pages/app/NewProject";
import { ProjectDetail } from "./pages/app/ProjectDetail";
import { Projects } from "./pages/app/Projects";
import { Settings } from "./pages/app/Settings";
import { Summarize } from "./pages/app/Summarize";
import { Landing } from "./pages/landing/Landing";
import { Login } from "./pages/Login";
import { NotFound } from "./pages/NotFound";
import { Privacy } from "./pages/Privacy";
import { Signup } from "./pages/Signup";
import { Terms } from "./pages/Terms";
import { Viewer } from "./pages/Viewer";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <RootLayout />,
    children: [
      { index: true, element: <Landing /> },
      { path: "terms", element: <Terms /> },
      { path: "privacy", element: <Privacy /> },
      // Public: a Viewer has no account.
      { path: "view/:shareId", element: <Viewer /> },
      {
        // Guest-only: a signed-in user goes on to the app.
        loader: redirectIfSignedIn,
        HydrateFallback: SessionPending,
        children: [
          { path: "login", element: <Login /> },
          { path: "signup", element: <Signup /> },
        ],
      },
      {
        // Signed-in only; the clip editor is full-screen, outside AppLayout, but guarded the same way.
        id: AUTH_ROUTE_ID,
        loader: requireUser,
        HydrateFallback: SessionPending,
        errorElement: <SessionError />,
        children: [
          {
            path: "app",
            element: <AppLayout />,
            children: [
              { index: true, element: <Projects /> },
              { path: "new", element: <NewProject /> },
              { path: "summarize", element: <Summarize /> },
              { path: "projects/:projectId", element: <ProjectDetail /> },
              { path: "projects/:projectId/clips/:clipId", element: <ClipDetail /> },
              { path: "settings", element: <Settings /> },
            ],
          },
          { path: "app/projects/:projectId/clips/:clipId/edit", element: <ClipEditor /> },
        ],
      },
      { path: "*", element: <NotFound /> },
    ],
  },
]);