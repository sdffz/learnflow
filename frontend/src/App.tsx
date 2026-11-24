import {
  BookOpenCheck,
  BrainCircuit,
  ChartNoAxesCombined,
  FolderKanban,
  GraduationCap,
  Home,
  LibraryBig,
  LoaderCircle,
  LogOut,
  Map,
  Plus,
  Route,
  Sparkles,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { api, authApi, knowledgeApi } from "./api";
import CaptureDialog from "./components/CaptureDialog";
import WorkspaceBar from "./components/WorkspaceBar";
import AssetDetailPage from "./pages/AssetDetailPage";
import AssessmentPage from "./pages/AssessmentPage";
import AuthPage from "./pages/AuthPage";
import CourseDetailPage from "./pages/CourseDetailPage";
import CoursesPage from "./pages/CoursesPage";
import KnowledgeDashboardPage from "./pages/KnowledgeDashboardPage";
import KnowledgePage from "./pages/KnowledgePage";
import PathPage from "./pages/PathPage";
import ProfilePage from "./pages/ProfilePage";
import StudioPage from "./pages/StudioPage";
import TutorPage from "./pages/TutorPage";
import type {
  AssetDetail,
  AuthContext,
  Course,
  CourseInput,
  KnowledgeOverview,
  Learner,
  LearnerProfile,
  ProfileUpdate,
} from "./types";
import {
  clearWorkspace,
  createDefaultWorkspace,
  loadWorkspace,
  saveWorkspace,
  type WorkspaceState,
  type WorkspaceTarget,
  workspaceStorageKey,
} from "./workspace";

type AppTarget = WorkspaceTarget | "courses" | "knowledge";

const navigation = [
  { id: "home" as const, label: "知识首页", icon: Home },
  { id: "courses" as const, label: "知识文件夹", icon: FolderKanban },
  { id: "knowledge" as const, label: "知识库", icon: LibraryBig },
  { id: "profile" as const, label: "学习画像", icon: BrainCircuit },
  { id: "studio" as const, label: "智能生成", icon: Sparkles },
  { id: "path" as const, label: "学习计划", icon: Route },
  { id: "tutor" as const, label: "智能辅导", icon: GraduationCap },
  {
    id: "assessment" as const,
    label: "效果评估",
    icon: ChartNoAxesCombined,
  },
];

const headings: Record<AppTarget, { title: string; subtitle: string }> = {
  home: { title: "知识工作台", subtitle: "PERSONAL KNOWLEDGE WORKSPACE" },
  courses: { title: "知识文件夹", subtitle: "PERSONAL KNOWLEDGE FOLDERS" },
  knowledge: { title: "知识库", subtitle: "PERSONAL KNOWLEDGE SEARCH" },
  profile: { title: "学习画像", subtitle: "PROFILE & EVIDENCE" },
  studio: { title: "智能生成", subtitle: "MULTI-AGENT RESOURCE STUDIO" },
  path: { title: "学习计划", subtitle: "ADAPTIVE LEARNING ROUTE" },
  tutor: { title: "智能辅导", subtitle: "EVIDENCE-GROUNDED TUTOR" },
  assessment: { title: "效果评估", subtitle: "MASTERY & FEEDBACK" },
};

const LEARNER_STORAGE_PREFIX = "learnflow_learner";

function learnerStorageKey(userId: string): string {
  return `${LEARNER_STORAGE_PREFIX}:${userId}`;
}

function readStoredLearner(userId: string): Learner | null {
  try {
    const raw = localStorage.getItem(learnerStorageKey(userId));
    return raw ? (JSON.parse(raw) as Learner) : null;
  } catch {
    return null;
  }
}

function messageFor(caught: unknown, fallback: string): string {
  return caught instanceof Error ? caught.message : fallback;
}

function App() {
  const [authStatus, setAuthStatus] = useState<
    "loading" | "anonymous" | "authenticated"
  >("loading");
  const [authContext, setAuthContext] = useState<AuthContext | null>(null);
  const [authError, setAuthError] = useState<string | null>(null);
  const [active, setActiveState] = useState<AppTarget>("home");
  const [learner, setLearner] = useState<Learner | null>(null);
  const [workspace, setWorkspace] = useState<WorkspaceState>(
    createDefaultWorkspace(),
  );
  const [overview, setOverview] = useState<KnowledgeOverview | null>(null);
  const [courses, setCourses] = useState<Course[]>([]);
  const [knowledgeLoading, setKnowledgeLoading] = useState(true);
  const [knowledgeError, setKnowledgeError] = useState<string | null>(null);
  const [activeCourseId, setActiveCourseId] = useState<string | null>(null);
  const [activeAssetId, setActiveAssetId] = useState<string | null>(null);
  const [assetSource, setAssetSource] = useState<AppTarget>("home");
  const [courseRevision, setCourseRevision] = useState(0);
  const [courseCreateRequested, setCourseCreateRequested] = useState(false);
  const [captureOpen, setCaptureOpen] = useState(false);
  const [captureCourseId, setCaptureCourseId] = useState<string | undefined>();
  const [creatingLearner, setCreatingLearner] = useState(false);
  const [learnerCreationError, setLearnerCreationError] = useState<
    string | null
  >(null);

  useEffect(() => {
    let activeRequest = true;
    authApi
      .me()
      .then((context) => {
        if (!activeRequest) return;
        if (!context) {
          setAuthStatus("anonymous");
          return;
        }
        setAuthContext(context);
        setAuthStatus("authenticated");
      })
      .catch((caught) => {
        if (!activeRequest) return;
        setAuthError(messageFor(caught, "账号服务暂时不可用"));
        setAuthStatus("anonymous");
      });
    return () => {
      activeRequest = false;
    };
  }, []);

  useEffect(() => {
    const handleUnauthorized = () => {
      if (authContext) {
        localStorage.removeItem(learnerStorageKey(authContext.user.id));
        clearWorkspace(workspaceStorageKey(authContext.user.id));
      }
      setAuthContext(null);
      setAuthStatus("anonymous");
      setLearner(null);
      setWorkspace(createDefaultWorkspace());
      setOverview(null);
      setCourses([]);
      setActiveState("home");
      setActiveAssetId(null);
      setActiveCourseId(null);
    };
    window.addEventListener("learnflow:unauthorized", handleUnauthorized);
    return () => {
      window.removeEventListener("learnflow:unauthorized", handleUnauthorized);
    };
  }, [authContext]);

  useEffect(() => {
    if (!authContext) {
      setLearner(null);
      setWorkspace(createDefaultWorkspace());
      return;
    }
    const storedLearner = readStoredLearner(authContext.user.id);
    const key = workspaceStorageKey(authContext.user.id);
    const storedWorkspace = loadWorkspace(key);
    setLearner(storedLearner);
    setWorkspace(
      storedLearner &&
        storedWorkspace.courseId === storedLearner.course_id
        ? storedWorkspace
        : createDefaultWorkspace(),
    );
  }, [authContext]);

  useEffect(() => {
    if (!authContext) return;
    const key = workspaceStorageKey(authContext.user.id);
    if (learner) saveWorkspace(workspace, key);
    else clearWorkspace(key);
  }, [authContext, learner, workspace]);

  const loadKnowledge = useCallback(async () => {
    setKnowledgeLoading(true);
    setKnowledgeError(null);
    try {
      const [nextOverview, nextCourses] = await Promise.all([
        knowledgeApi.getOverview(),
        knowledgeApi.listCourses(),
      ]);
      setOverview(nextOverview);
      setCourses(nextCourses);
    } catch (caught) {
      setKnowledgeError(messageFor(caught, "个人知识空间暂时无法加载"));
    } finally {
      setKnowledgeLoading(false);
    }
  }, []);

  useEffect(() => {
    if (authStatus === "authenticated") void loadKnowledge();
  }, [authStatus, loadKnowledge]);

  const persistLearner = (value: Learner | null) => {
    setLearner(value);
    if (!authContext) return;
    const key = learnerStorageKey(authContext.user.id);
    if (value) localStorage.setItem(key, JSON.stringify(value));
    else localStorage.removeItem(key);
  };

  const createPersonalLearner = async () => {
    if (creatingLearner) return;
    setCreatingLearner(true);
    setLearnerCreationError(null);
    try {
      const created = await api.createPersonalLearner(
        authContext?.user.name ?? "我的学习空间",
      );
      persistLearner(created);
      setWorkspace(createDefaultWorkspace());
      setActiveState("profile");
    } catch (caught) {
      setLearnerCreationError(messageFor(caught, "个人学习画像创建失败"));
    } finally {
      setCreatingLearner(false);
    }
  };

  const updateProfile = (update: ProfileUpdate | LearnerProfile) => {
    if (!learner) return;
    const profile = "profile" in update ? update.profile : update;
    persistLearner({ ...learner, profile });
  };

  const handleAuthenticated = (context: AuthContext) => {
    setAuthContext(context);
    setAuthStatus("authenticated");
    setAuthError(null);
    setActiveState("home");
  };

  const logout = async () => {
    try {
      await authApi.logout();
    } finally {
      if (authContext) {
        localStorage.removeItem(learnerStorageKey(authContext.user.id));
        clearWorkspace(workspaceStorageKey(authContext.user.id));
      }
      setAuthContext(null);
      setAuthStatus("anonymous");
      setLearner(null);
      setWorkspace(createDefaultWorkspace());
      setOverview(null);
      setCourses([]);
      setActiveState("home");
      setActiveAssetId(null);
      setActiveCourseId(null);
    }
  };

  const navigate = useCallback((target: AppTarget) => {
    setActiveState(target);
    setActiveAssetId(null);
    if (target === "courses") setCourseCreateRequested(false);
    if (target !== "courses") setActiveCourseId(null);
    if (target === "home" || target === "knowledge") {
      void loadKnowledge();
    }
  }, [loadKnowledge]);

  const openCourse = (courseId: string) => {
    setActiveCourseId(courseId);
    setActiveAssetId(null);
    setActiveState("courses");
  };

  const openAsset = (assetId: string) => {
    setAssetSource(active);
    setActiveAssetId(assetId);
  };

  const closeAsset = () => {
    setActiveAssetId(null);
    setActiveState(assetSource);
  };

  const openCapture = (courseId?: string) => {
    setCaptureCourseId(
      courseId ?? activeCourseId ?? courses[0]?.id ?? undefined,
    );
    setCaptureOpen(true);
  };

  const createCourse = async (input: CourseInput) => {
    const created = await knowledgeApi.createCourse(input);
    setCourseCreateRequested(false);
    await loadKnowledge();
    return created;
  };

  const updateCourse = async (courseId: string, input: CourseInput) => {
    const updated = await knowledgeApi.updateCourse(courseId, input);
    await loadKnowledge();
    return updated;
  };

  const openCourseCreate = () => {
    setCourseCreateRequested(true);
    setActiveCourseId(null);
    setActiveAssetId(null);
    setActiveState("courses");
  };

  const deleteCourse = async (courseId: string) => {
    await knowledgeApi.deleteCourse(courseId);
    if (activeCourseId === courseId) setActiveCourseId(null);
    await loadKnowledge();
  };

  const assetCreated = (asset: AssetDetail) => {
    setCourseRevision((value) => value + 1);
    void loadKnowledge();
    if (!activeCourseId) setCaptureCourseId(asset.courseId);
  };

  const updateWorkspace = useCallback((patch: Partial<WorkspaceState>) => {
    setWorkspace((current) => ({ ...current, ...patch }));
  }, []);

  if (authStatus === "loading") {
    return (
      <main className="auth-loading">
        <LoaderCircle className="spin" size={24} />
        正在验证你的私有工作空间
      </main>
    );
  }

  if (authStatus === "anonymous") {
    return (
      <AuthPage
        initialError={authError}
        onAuthenticated={handleAuthenticated}
      />
    );
  }

  const activeCourse =
    courses.find((course) => course.id === activeCourseId) ?? null;
  const currentHeading = activeAssetId
    ? { title: "资料详情", subtitle: "KNOWLEDGE SOURCE" }
    : headings[active];
  const showWorkspaceBar =
    Boolean(learner) &&
    !activeAssetId &&
    active !== "home" &&
    active !== "courses" &&
    active !== "knowledge";

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <button className="brand" onClick={() => navigate("home")}>
          <span className="brand-mark">
            <BookOpenCheck size={25} strokeWidth={1.8} />
          </span>
          <span>
            <strong>知序 LearnFlow</strong>
            <small>个人知识管理与学习智能体</small>
          </span>
        </button>

        <nav aria-label="主要导航">
          {navigation.map((item) => {
            const Icon = item.icon;
            return (
              <button
                className={active === item.id ? "nav-item active" : "nav-item"}
                key={item.id}
                onClick={() => navigate(item.id)}
                aria-current={active === item.id ? "page" : undefined}
              >
                <Icon size={19} strokeWidth={1.8} />
                {item.label}
              </button>
            );
          })}
        </nav>

        <div className="sidebar-note">
          <Map size={17} />
          <div>
            <strong>私有知识空间</strong>
            <span>
              {overview?.courseCount ?? 0} 个文件夹 ·{" "}
              {overview?.assetCount ?? 0} 份资料
            </span>
          </div>
        </div>
      </aside>

      <main className="workspace">
        <header className="topbar">
          <div>
            <span className="eyebrow">{currentHeading.subtitle}</span>
            <h1>{currentHeading.title}</h1>
          </div>
          <div className="topbar-actions">
            <button
              className="primary-button topbar-capture"
              aria-label="打开添加知识"
              onClick={() => openCapture()}
            >
              <Plus size={17} />
              添加
            </button>
            <button
              className="learner-chip"
              aria-label={`${authContext!.user.name} 我的学习画像`}
              onClick={() => navigate("profile")}
            >
              <span>{authContext!.user.name.slice(0, 1)}</span>
              <div>
                <strong>{authContext!.user.name}</strong>
                <small>{authContext!.workspace.name}</small>
              </div>
              <BrainCircuit size={14} />
            </button>
            <button
              className="logout-button"
              aria-label="退出登录"
              title="退出登录"
              onClick={() => void logout()}
            >
              <LogOut size={17} />
            </button>
            <div className="mode-chip">
              <span className="status-dot" />
              演示模型
            </div>
          </div>
        </header>

        {showWorkspaceBar ? (
          <WorkspaceBar
            learner={learner!}
            workspace={workspace}
            active={active as WorkspaceTarget}
            onNavigate={navigate}
          />
        ) : null}

        {activeAssetId ? (
          <AssetDetailPage assetId={activeAssetId} onBack={closeAsset} />
        ) : null}

        {!activeAssetId && active === "home" ? (
          <KnowledgeDashboardPage
            overview={overview}
            loading={knowledgeLoading}
            error={knowledgeError}
            onCapture={() => openCapture()}
            onOpenCourse={openCourse}
            onOpenAsset={openAsset}
            onOpenKnowledge={() => navigate("knowledge")}
            onCreateCourse={openCourseCreate}
            onRefresh={() => void loadKnowledge()}
          />
        ) : null}

        {!activeAssetId && active === "courses" ? (
          activeCourse ? (
            <CourseDetailPage
              key={`${activeCourse.id}-${courseRevision}`}
              course={activeCourse}
              onBack={() => {
                setActiveCourseId(null);
                void loadKnowledge();
              }}
              onCapture={openCapture}
              onOpenAsset={openAsset}
            />
          ) : (
            <CoursesPage
              courses={courses}
              loading={knowledgeLoading}
              error={knowledgeError}
              onCreate={createCourse}
              onUpdate={updateCourse}
              onOpen={openCourse}
              onRefresh={() => void loadKnowledge()}
              onDelete={deleteCourse}
              startCreating={courseCreateRequested}
            />
          )
        ) : null}

        {!activeAssetId && active === "knowledge" ? (
          <KnowledgePage
            tags={overview?.topTags ?? []}
            onOpenAsset={openAsset}
          />
        ) : null}

        {!activeAssetId && active === "profile" ? (
          <ProfilePage
            learner={learner}
            onProfileUpdated={updateProfile}
            onNeedLearner={() => void createPersonalLearner()}
            onCreatePersonalLearner={() => void createPersonalLearner()}
            creatingPersonalLearner={creatingLearner}
            learnerCreationError={learnerCreationError}
            onNavigate={navigate}
          />
        ) : null}

        {!activeAssetId && active === "studio" ? (
          <StudioPage
            learner={learner}
            onNeedLearner={() => void createPersonalLearner()}
            workspace={workspace}
            onWorkspaceChange={updateWorkspace}
            onNavigate={navigate}
            courses={courses}
          />
        ) : null}

        {!activeAssetId && active === "path" ? (
          <PathPage
            learner={learner}
            onNeedLearner={() => void createPersonalLearner()}
            onWorkspaceChange={updateWorkspace}
            onNavigate={navigate}
          />
        ) : null}

        {!activeAssetId && active === "tutor" ? (
          <TutorPage
            learner={learner}
            onNeedLearner={() => void createPersonalLearner()}
            workspace={workspace}
            onNavigate={navigate}
          />
        ) : null}

        {!activeAssetId && active === "assessment" ? (
          <AssessmentPage
            learner={learner}
            onNeedLearner={() => void createPersonalLearner()}
            onProfileUpdated={updateProfile}
            onAssessmentComplete={(score) =>
              updateWorkspace({
                lastAssessmentScore: score,
                lastAssessmentAt: new Date().toISOString(),
              })
            }
            onNavigate={navigate}
          />
        ) : null}
      </main>

      {captureOpen ? (
        <CaptureDialog
          courses={courses}
          initialCourseId={captureCourseId}
          onClose={() => {
            setCaptureOpen(false);
            void loadKnowledge();
          }}
          onCreated={assetCreated}
        />
      ) : null}
    </div>
  );
}

export default App;
