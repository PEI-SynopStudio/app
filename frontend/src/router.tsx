import { createBrowserRouter } from "react-router";
import { AppLayout } from "./layouts/AppLayout";
import { RootLayout } from "./layouts/RootLayout";
import { ClipEditor } from "./pages/app/ClipEditor";
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
      { path: "login", element: <Login /> },
      { path: "signup", element: <Signup /> },
      { path: "terms", element: <Terms /> },
      { path: "privacy", element: <Privacy /> },
      { path: "view/:shareId", element: <Viewer /> },
      {
        path: "app",
        element: <AppLayout />,
        children: [
          { index: true, element: <Projects /> },
          { path: "new", element: <NewProject /> },
          { path: "summarize", element: <Summarize /> },
          { path: "projects/:projectId", element: <ProjectDetail /> },
          { path: "settings", element: <Settings /> },
        ],
      },
      { path: "app/projects/:projectId/clips/:clipId", element: <ClipEditor /> },
      { path: "*", element: <NotFound /> },
    ],
  },
]);