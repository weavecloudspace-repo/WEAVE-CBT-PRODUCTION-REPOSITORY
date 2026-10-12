import { toStudentResolution } from './studentResolution';
import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { appReducer, createInitialState } from "./state/appState";

import { parseStaffPath, pathForStaffState, staffPatchFromRoute, staffSectionForRole } from "./staffNavigation";

const NAV_STATE_KEY = "weave.cbt.navigation";
const setupViews = new Set([
  "welcome",
  "pairing-code",
  "server-name",
  "pairing",
  "paired-success",
]);
const applications = new Set(["combined", "staff", "student"]);

export function useAppController({ application = "combined", gateway } = {}) {
  if (!applications.has(application)) {
    throw new Error(
      `Unsupported Weave CBT frontend application: ${application}`,
    );
  }
  if (!gateway) {
    throw new Error("A scoped Weave CBT frontend gateway is required");
  }

  const navigate = useNavigate();
  const location = useLocation();
  const [state, rawDispatch] = useReducer(
    appReducer,
    undefined,
    createInitialState,
  );
  const [studentSuspension, setStudentSuspension] = useState(null);
  const pairPending = useRef(false);
  const bootPending = useRef(true);
  const stateRef = useRef(state);
  const locationPathRef = useRef(location.pathname + location.search);
  const navigateRef = useRef(navigate);

  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  useEffect(() => {
    locationPathRef.current = location.pathname + location.search;
  }, [location.pathname, location.search]);

  useEffect(() => {
    navigateRef.current = navigate;
  }, [navigate]);

  const routeDispatch = useCallback(
    (action) => {
      rawDispatch(action);
      const current = stateRef.current;
      const nextPath = pathForAction(action, current, application);
      if (nextPath) navigate(nextPath);
    },
    [application, navigate],
  );

  const restoreSession = useCallback(async () => {
    const savedNavigation = readNavigationState();
    const routeNavigation = routeToNavigation(
      routeFromPath(locationPathRef.current, application),
    );
    const navigationTarget = { ...savedNavigation, ...routeNavigation };

    if (application === "staff") {
      return restoreStaffSession(
        rawDispatch,
        navigationTarget,
        navigateRef.current,
        gateway,
      );
    }
    if (application === "student") {
      return restoreStudentSession(
        rawDispatch,
        navigationTarget,
        navigateRef.current,
        gateway,
      );
    }

    const preferredType = navigationTarget?.sessionType;
    const restorers =
      preferredType === "student"
        ? [restoreStudentSession, restoreStaffSession]
        : [restoreStaffSession, restoreStudentSession];

    for (const restore of restorers) {
      if (
        await restore(
          rawDispatch,
          navigationTarget,
          navigateRef.current,
          gateway,
        )
      )
        return true;
    }
    return false;
  }, [application, gateway]);

  const boot = useCallback(
    async (signal) => {
      bootPending.current = true;
      rawDispatch({ type: "bootStart" });
      gateway.branding
        .getBranding({ signal })
        .then((branding) => rawDispatch({ type: "brandingSuccess", branding }))
        .catch(() => null);
      try {
        const status = await gateway.installation.getInstallationStatus({
          signal,
        });
        rawDispatch({
          type: "bootSuccess",
          status,
          view: status.configured
            ? "boot"
            : application === "student"
              ? "student-unavailable"
              : undefined,
        });
        if (status.configured) {
          const restored = await restoreSession();
          if (!restored) {
            applyRouteToState(
              routeFromPath(locationPathRef.current, application),
              stateRef.current,
              rawDispatch,
              navigateRef.current,
            );
          }
        } else if (application === "student") {
          rawDispatch({ type: "view", view: "student-unavailable" });
          navigateRef.current("/", { replace: true });
        } else {
          const route = routeFromPath(locationPathRef.current, application);
          if (setupViews.has(route.view)) {
            rawDispatch({ type: "view", view: route.view });
            navigateRef.current(pathForView(route.view, application), {
              replace: true,
            });
          } else {
            navigateRef.current("/setup", { replace: true });
          }
        }
      } catch (error) {
        if (error.name !== "AbortError") {
          rawDispatch({
            type: "bootFailure",
            message:
              error.userMessage || "Weave could not reach the local backend.",
          });
        }
      } finally {
        if (!signal?.aborted) bootPending.current = false;
      }
    },
    [application, gateway, restoreSession],
  );

  useEffect(() => {
    const controller = new AbortController();
    boot(controller.signal);
    return () => controller.abort();
  }, [boot]);

  useEffect(() => {
    if (state.installation.loading || bootPending.current) return;
    if (!state.installation.configured) {
      if (application === "student") {
        rawDispatch({ type: "view", view: "student-unavailable" });
        if (normalizePath(location.pathname) !== "/")
          navigate("/", { replace: true });
        return;
      }

      const route = routeFromPath(location.pathname + location.search, application);
      if (setupViews.has(route.view)) {
        rawDispatch({ type: "view", view: route.view });
        return;
      }
      rawDispatch({ type: "view", view: "welcome" });
      navigate("/setup", { replace: true });
      return;
    }

    const route = routeFromPath(location.pathname + location.search, application);
    // Pairing state can commit before the router finishes its navigation.
    // Preserve the success screen while the old pairing URL is still current.
    if (application !== "student" && (
      route.view === "paired-success" ||
      (route.view === "pairing" && stateRef.current.view === "paired-success")
    )) {
      rawDispatch({ type: "view", view: "paired-success" });
      if (route.view !== "paired-success") navigate("/setup/paired-success", { replace: true });
      return;
    }
    if (setupViews.has(route.view)) {
      rawDispatch({ type: "view", view: "landing" });
      navigate("/", { replace: true });
      return;
    }
    applyRouteToState(route, stateRef.current, rawDispatch, navigate);
  }, [
    application,
    location.pathname,
    location.search,
    navigate,
    state.installation.configured,
    state.installation.loading,
  ]);

  const pair = useCallback(
    async (form) => {
      if (application === "student" || pairPending.current) return;
      pairPending.current = true;
      rawDispatch({ type: "setupStart" });
      navigate("/setup/pairing");
      try {
        const status = await gateway.installation.pairInstallation(form);
        rawDispatch({ type: "setupSuccess", status });
        navigate("/setup/paired-success", { replace: true });
        gateway.branding
          .getBranding()
          .then((branding) =>
            rawDispatch({ type: "brandingSuccess", branding }),
          )
          .catch(() => null);
      } catch (error) {
        if (error.status === 409) {
          try {
            const status = await gateway.installation.getInstallationStatus();
            if (status.configured) {
              rawDispatch({ type: "setupSuccess", status });
              navigate("/setup/paired-success", { replace: true });
              gateway.branding
                .getBranding()
                .then((branding) =>
                  rawDispatch({ type: "brandingSuccess", branding }),
                )
                .catch(() => null);
              return;
            }
          } catch {
            /* Keep the setup values available for a retry. */
          }
        }
        rawDispatch({
          type: "setupFailure",
          message: error.userMessage || "Pairing failed. Try again.",
        });
      } finally {
        pairPending.current = false;
      }
    },
    [application, gateway, navigate],
  );

  const signInStaff = useCallback(
    async ({ email, password }) => {
      if (application === "student") return;
      rawDispatch({ type: "authStart" });
      try {
        const session = await gateway.auth.loginStaff({ email, password });
        if (session.role === "teacher") {
          rawDispatch({ type: "authSuccess", session, view: "staff" });
          rawDispatch({ type: "staff", patch: { section: "overview" } });
          navigate("/teacher/overview", { replace: true });
        } else if (session.role === "admin") {
          rawDispatch({ type: "authSuccess", session, view: "sync-check" });
          rawDispatch({ type: "syncChecking" });
          navigate("/sync/check", { replace: true });
          try {
            const status = await gateway.sync.getSyncStatus();
            rawDispatch({ type: "syncStatus", status });
            navigate(
              status.bootstrap_completed_at
                ? "/admin/dashboard"
                : "/sync/initial",
              { replace: true },
            );
          } catch (error) {
            rawDispatch({
              type: "syncFailure",
              message: error.userMessage || "Could not check server readiness.",
            });
            navigate("/sync/initial", { replace: true });
          }
        } else {
          gateway.auth
            .signOutStaff()
            .catch(() => gateway.auth.clearStaffSession());
          rawDispatch({
            type: "authFailure",
            message: "This account has no CBT staff workspace.",
          });
        }
      } catch (error) {
        rawDispatch({
          type: "authFailure",
          message: error.userMessage || "Staff sign in failed.",
        });
      }
    },
    [application, gateway, navigate],
  );

  const signInStudent = useCallback(
    async ({ admissionNumber, password }) => {
      if (application === "staff") return;
      rawDispatch({ type: "authStart" });
      try {
        const session = await gateway.auth.loginStudent({
          admissionNumber,
          password,
        });
        rawDispatch({
          type: "authSuccess",
          session,
          view: "student",
          examStage: "lobby",
        });
        rawDispatch({
          type: "studentResolution",
          resolution: toStudentResolution(session),
        });
        navigate("/student", { replace: true });
      } catch (error) {
        rawDispatch({
          type: "authFailure",
          message: error.userMessage || "Student sign in failed.",
        });
      }
    },
    [application, gateway, navigate],
  );

  useEffect(() => {
    if (application === "staff") return undefined;

    const waitingState = state.studentResolution?.state;
    const shouldPoll =
      state.session?.type === "student" &&
      state.view === "student" &&
      state.exam.stage === "lobby" &&
      (waitingState === "no_exam" ||
        waitingState === "waiting_for_activation" ||
        waitingState === "suspended");
    if (!shouldPoll) return undefined;

    let cancelled = false;
    const refresh = async () => {
      try {
        const session = await gateway.auth.getStudentStatus();
        if (!cancelled) {
          rawDispatch({
            type: "studentResolution",
            resolution: toStudentResolution(session),
          });
        }
      } catch (error) {
        if (!cancelled && error.status === 401) {
          rawDispatch({ type: "signOut" });
          navigate("/", { replace: true });
        }
      }
    };

    const interval = window.setInterval(refresh, 5000);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [
    application,
    gateway,
    state.session?.type,
    state.view,
    state.exam.stage,
    state.studentResolution?.state,
    navigate,
  ]);

  useEffect(() => {
    persistNavigationState({
      view: state.view,
      sessionType: state.session?.type,
      role: state.session?.role,
      staffSection: state.staff.section,
      selectedQuestionId: state.staff.selectedQuestionId,
      selectedAIDraftId: state.staff.selectedAIDraftId,
      selectedExamId: state.staff.selectedExamId,
      selectedBankId: state.staff.selectedBankId,
      timetableLevelId: state.staff.timetableLevelId,
      questionPreviewOrigin: state.staff.questionPreviewOrigin,
      examStage: state.exam.stage,
    });
  }, [
    state.view,
    state.session?.type,
    state.session?.role,
    state.staff,
    state.exam.stage,
  ]);

  const signOut = useCallback(async () => {
    if (state.session?.type === "student" && application !== "staff") {
      await gateway.auth.logoutStudent().catch(() => null);
    }
    if (state.session?.type === "staff" && application !== "student") {
      await gateway.auth
        .signOutStaff()
        .catch(() => gateway.auth.clearStaffSession());
    }
    clearNavigationState();
    rawDispatch({ type: "signOut" });
    navigate("/", { replace: true });
  }, [application, gateway, navigate, state.session]);

  const handleStudentSuspension = useCallback((message) => {
    const statusMessage =
      message ||
      "Your examination has been suspended. Stay in the waiting room until it is resumed.";
    const currentResolution = stateRef.current.studentResolution;

    setStudentSuspension({ message: statusMessage });
    if (currentResolution) {
      rawDispatch({
        type: "studentResolution",
        resolution: {
          ...currentResolution,
          state: "suspended",
          statusMessage,
        },
      });
    }
    rawDispatch({ type: "exam", patch: { stage: "lobby", index: 0 } });
    navigate("/student", { replace: true });
  }, [navigate]);

  return {
    studentSuspension,
    dismissStudentSuspension: () => setStudentSuspension(null),
    handleStudentSuspension,
    state,
    dispatch: routeDispatch,
    boot,
    pair,
    signInStaff,
    signInStudent,
    signOut,
  };
}

async function restoreStudentSession(
  dispatch,
  savedNavigation,
  navigate,
  gateway,
) {
  try {
    const session = await gateway.auth.getStudentStatus();
    const examStage =
      savedNavigation?.examStage === "active" && session.availability !== "suspended"
        ? "active"
        : "lobby";
    dispatch({ type: "authSuccess", session, view: "student", examStage });
    dispatch({
      type: "studentResolution",
      resolution: toStudentResolution(session),
    });
    navigate(examStage === "active" ? "/student/exam" : "/student", {
      replace: true,
    });
    return true;
  } catch {
    return false;
  }
}

async function restoreStaffSession(
  dispatch,
  savedNavigation,
  navigate,
  gateway,
) {
  try {
    const session = await gateway.auth.refreshStaff();
    if (session.role === "teacher") {
      const section = staffSectionForRole(
        session.role,
        savedNavigation?.staffSection,
      );
      dispatch({ type: "authSuccess", session, view: "staff" });
      const staff = staffPatchFromRoute({ ...savedNavigation, role: session.role, staffSection: section });
      dispatch({ type: "staff", patch: staff });
      navigate(pathForStaffState({ session, staff }), { replace: true });
      return true;
    }
    if (session.role === "admin") {
      const section = staffSectionForRole(
        session.role,
        savedNavigation?.staffSection,
      );
      dispatch({ type: "authSuccess", session, view: "sync-check" });
      const staff = staffPatchFromRoute({ ...savedNavigation, role: session.role, staffSection: section });
      dispatch({ type: "staff", patch: staff });
      dispatch({ type: "syncChecking" });
      try {
        const status = await gateway.sync.getSyncStatus();
        dispatch({ type: "syncStatus", status });
        navigate(
          status.bootstrap_completed_at
            ? pathForStaffState({ session, staff })
            : "/sync/initial",
          { replace: true },
        );
      } catch (error) {
        dispatch({
          type: "syncFailure",
          message: error.userMessage || "Could not check server readiness.",
        });
        navigate("/sync/initial", { replace: true });
      }
      return true;
    }
    await gateway.auth
      .signOutStaff()
      .catch(() => gateway.auth.clearStaffSession());
    return false;
  } catch {
    gateway.auth.clearStaffSession();
    return false;
  }
}

function routeFromPath(pathname, application = "combined") {
  const route = routeFromPathUnchecked(pathname);

  if (application === "staff") {
    if (route.view === "student-login" || route.sessionType === "student") {
      return { view: "landing" };
    }
    return route;
  }

  if (application === "student") {
    if (
      route.view === "staff-login" ||
      route.sessionType === "staff" ||
      setupViews.has(route.view) ||
      route.view === "sync-check" ||
      route.view === "initial-sync"
    ) {
      return { view: "landing" };
    }
  }

  return route;
}

function routeFromPathUnchecked(pathname) {
  const path = normalizePath(pathname.split("?")[0]);
  if (path === "/") return { view: "landing" };
  if (path === "/student/login") return { view: "student-login" };
  if (path === "/staff/login") return { view: "staff-login" };
  if (path === "/setup") return { view: "welcome" };
  if (path.startsWith("/setup/")) {
    const view = path.slice("/setup/".length);
    return { view: setupViews.has(view) ? view : "welcome" };
  }
  if (path === "/sync/check") return { view: "sync-check" };
  if (path === "/sync/initial") return { view: "initial-sync" };
  if (path === "/student")
    return {
      view: "student",
      sessionType: "student",
      examStage: "lobby",
      requiresAuth: true,
    };
  if (path === "/student/exam")
    return {
      view: "student",
      sessionType: "student",
      examStage: "active",
      requiresAuth: true,
    };
  const staffRoute = parseStaffPath(pathname);
  if (staffRoute) return staffRoute;
  return { view: "landing" };
}

function routeToNavigation(route) {
  if (!route?.requiresAuth) return null;
  return {
    sessionType: route.sessionType,
    role: route.role,
    staffSection: route.staffSection,
    selectedQuestionId: route.selectedQuestionId,
    selectedAIDraftId: route.selectedAIDraftId,
    selectedExamId: route.selectedExamId,
    selectedBankId: route.selectedBankId,
    timetableLevelId: route.timetableLevelId,
    questionPreviewOrigin: route.questionPreviewOrigin,
    examStage: route.examStage,
  };
}

function applyRouteToState(route, state, dispatch, navigate) {
  if (route?.requiresAuth) {
    if (route.sessionType === "staff" && state.session?.type === "staff") {
      const rolePath = state.session.role === "admin" ? "admin" : "teacher";
      if (route.role && route.role !== state.session.role) {
        navigate(
          `/${rolePath}/${staffSectionForRole(state.session.role, state.staff.section)}`,
          { replace: true },
        );
        return;
      }
      dispatch({ type: "authSuccess", session: state.session, view: "staff" });
      dispatch({
        type: "staff",
        patch: staffPatchFromRoute(route),
      });
      return;
    }
    if (route.sessionType === "student" && state.session?.type === "student") {
      dispatch({
        type: "authSuccess",
        session: state.session,
        view: "student",
        examStage: route.examStage || "lobby",
      });
      if (state.studentResolution)
        dispatch({
          type: "studentResolution",
          resolution: state.studentResolution,
        });
      return;
    }
    const loginPath =
      route.sessionType === "student" ? "/student/login" : "/staff/login";
    dispatch({
      type: "view",
      view: route.sessionType === "student" ? "student-login" : "staff-login",
    });
    navigate(loginPath, { replace: true });
    return;
  }
  dispatch({ type: "view", view: route?.view || "landing" });
}

function pathForAction(action, state, application = "combined") {
  if (action.type === "view") return pathForView(action.view, application);
  if (action.type === "setupStart")
    return application === "student" ? "/" : "/setup/pairing";
  if (action.type === "setupSuccess")
    return application === "student" ? "/" : "/setup/paired-success";
  if (action.type === "signOut") return "/";
  if (action.type === "syncChecking")
    return application === "student" ? "/" : "/sync/check";
  if (action.type === "syncFailure")
    return application === "student" ? "/" : "/sync/initial";
  if (action.type === "syncStatus") {
    return application === "student"
      ? "/"
      : action.status.bootstrap_completed_at
        ? pathForStaffState(state)
        : "/sync/initial";
  }
  if (
    action.type === "staff" &&
    action.patch?.section &&
    state.session?.type === "staff"
  ) {
    return application === "student"
      ? "/"
      : pathForStaffState({
          ...state,
          staff: { ...state.staff, ...action.patch },
        });
  }
  if (
    action.type === "exam" &&
    action.patch?.stage &&
    state.session?.type === "student"
  ) {
    if (application === "staff") return "/";
    return action.patch.stage === "active" ? "/student/exam" : "/student";
  }
  return null;
}

function pathForView(view, application = "combined") {
  if (view === "landing") return "/";
  if (view === "student-login")
    return application === "staff" ? "/" : "/student/login";
  if (view === "staff-login")
    return application === "student" ? "/" : "/staff/login";
  if (setupViews.has(view)) {
    if (application === "student") return "/";
    return view === "welcome" ? "/setup" : `/setup/${view}`;
  }
  if (view === "sync-check")
    return application === "student" ? "/" : "/sync/check";
  if (view === "initial-sync")
    return application === "student" ? "/" : "/sync/initial";
  return null;
}

function normalizePath(pathname) {
  const path = pathname || "/";
  if (path.length > 1 && path.endsWith("/")) return path.slice(0, -1);
  return path;
}

function readNavigationState() {
  try {
    const raw = window.localStorage.getItem(NAV_STATE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function persistNavigationState({
  view,
  sessionType,
  role,
  staffSection,
  selectedQuestionId,
  selectedAIDraftId,
  selectedExamId,
  selectedBankId,
  timetableLevelId,
  questionPreviewOrigin,
  examStage,
}) {
  if (sessionType === "staff" && view === "staff") {
    window.localStorage.setItem(
      NAV_STATE_KEY,
      JSON.stringify({
        sessionType: "staff",
        role,
        staffSection,
        selectedAIDraftId,
        selectedExamId,
        selectedBankId,
        timetableLevelId,
        questionPreviewOrigin,
        selectedQuestionId:
          staffSection === "preview-question" ||
          staffSection === "edit-question"
            ? selectedQuestionId
            : null,
      }),
    );
    return;
  }
  if (sessionType === "student" && view === "student") {
    window.localStorage.setItem(
      NAV_STATE_KEY,
      JSON.stringify({
        sessionType: "student",
        examStage,
      }),
    );
  }
}

function clearNavigationState() {
  window.localStorage.removeItem(NAV_STATE_KEY);
}