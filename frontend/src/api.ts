import type {
  AgentEvent,
  AssetDetail,
  AssessmentQuestion,
  AssessmentResult,
  AuthContext,
  Course,
  CourseInput,
  KnowledgeAsset,
  KnowledgeChunk,
  KnowledgeList,
  KnowledgeOverview,
  KnowledgeSearchResult,
  Learner,
  LearningConnectorStatus,
  LearningFolderMapping,
  LearningImportDetail,
  LearningImportJob,
  LearningImportPreview,
  LearningLogin,
  LearningLoginResult,
  LearningPath,
  Persona,
  ProfileUpdate,
  RunSnapshot,
  TutorAnswer,
} from "./types";
import { resolveApiBase } from "./config";

const API_BASE = resolveApiBase(
  import.meta.env.VITE_API_BASE_URL,
  import.meta.env.DEV,
);

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });
  if (
    response.status === 401 &&
    !path.startsWith("/auth/") &&
    typeof window !== "undefined"
  ) {
    window.dispatchEvent(new Event("learnflow:unauthorized"));
  }
  if (!response.ok) {
    await throwRequestError(response);
  }
  return response.json() as Promise<T>;
}

async function throwRequestError(response: Response): Promise<never> {
  const body = await response.json().catch(() => ({}));
  throw new ApiError(
    body.detail ?? `请求失败：${response.status}`,
    response.status,
  );
}

async function formRequest<T>(
  path: string,
  body: FormData,
  method = "POST",
): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method,
    body,
    credentials: "include",
  });
  if (
    response.status === 401 &&
    typeof window !== "undefined"
  ) {
    window.dispatchEvent(new Event("learnflow:unauthorized"));
  }
  if (!response.ok) await throwRequestError(response);
  return response.json() as Promise<T>;
}

async function emptyRequest(path: string, method = "DELETE"): Promise<void> {
  const response = await fetch(`${API_BASE}${path}`, {
    method,
    credentials: "include",
  });
  if (
    response.status === 401 &&
    typeof window !== "undefined"
  ) {
    window.dispatchEvent(new Event("learnflow:unauthorized"));
  }
  if (!response.ok) await throwRequestError(response);
}

export const authApi = {
  async me(): Promise<AuthContext | null> {
    const response = await fetch(`${API_BASE}/auth/me`, {
      credentials: "include",
    });
    if (response.status === 401) return null;
    if (!response.ok) await throwRequestError(response);
    return response.json() as Promise<AuthContext>;
  },

  login(email: string, password: string): Promise<AuthContext> {
    return request("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
  },

  register(
    name: string,
    email: string,
    password: string,
  ): Promise<AuthContext> {
    return request("/auth/register", {
      method: "POST",
      body: JSON.stringify({
        name,
        email,
        password,
      }),
    });
  },

  logout(): Promise<void> {
    return emptyRequest("/auth/logout", "POST");
  },
};

export const api = {
  async getPersonas(): Promise<Persona[]> {
    const payload = await request<{ personas: Persona[] }>("/personas");
    return payload.personas;
  },

  createLearner(personaId: string): Promise<Learner> {
    return request("/learners", {
      method: "POST",
      body: JSON.stringify({ persona_id: personaId }),
    });
  },

  createPersonalLearner(name = "我的学习空间"): Promise<Learner> {
    return request("/learners", {
      method: "POST",
      body: JSON.stringify({ name }),
    });
  },

  chatProfile(learnerId: string, message: string): Promise<ProfileUpdate> {
    return request(`/learners/${learnerId}/profile/chat`, {
      method: "POST",
      body: JSON.stringify({ message }),
    });
  },

  createRun(learnerId: string, topic: string, courseId?: string) {
    return request<{ id: string }>(`/learners/${learnerId}/runs`, {
      method: "POST",
      body: JSON.stringify({
        topic,
        ...(courseId ? { courseId } : {}),
      }),
    });
  },

  getRun(runId: string): Promise<RunSnapshot> {
    return request(`/runs/${runId}`);
  },

  async streamRun(
    runId: string,
    onEvent: (event: AgentEvent) => void,
  ): Promise<void> {
    const response = await fetch(`${API_BASE}/runs/${runId}/stream`);
    if (!response.ok || !response.body) {
      throw new Error("无法连接生成进度流");
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    const consume = (block: string) => {
      const data = block
        .split("\n")
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).trim())
        .join("\n");
      if (!data) return;
      try {
        onEvent(JSON.parse(data) as AgentEvent);
      } catch {
        // A malformed event must not freeze the rest of the stream.
      }
    };

    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      const blocks = buffer.split("\n\n");
      buffer = blocks.pop() ?? "";
      blocks.forEach(consume);
      if (done) break;
    }
    if (buffer.trim()) consume(buffer);
  },

  createPath(learnerId: string): Promise<LearningPath> {
    return request(`/learners/${learnerId}/paths`, { method: "POST" });
  },

  markPathNode(
    learnerId: string,
    nodeId: string,
    completed: boolean,
  ): Promise<LearningPath> {
    return request(`/learners/${learnerId}/paths/${encodeURIComponent(nodeId)}`, {
      method: "POST",
      body: JSON.stringify({ completed }),
    });
  },

  askTutor(learnerId: string, question: string): Promise<TutorAnswer> {
    return request(`/learners/${learnerId}/tutor`, {
      method: "POST",
      body: JSON.stringify({ question }),
    });
  },

  async getAssessmentQuestions(): Promise<AssessmentQuestion[]> {
    const payload = await request<{ questions: AssessmentQuestion[] }>(
      "/assessments/questions",
    );
    return payload.questions;
  },

  submitAssessment(
    learnerId: string,
    answers: Record<string, number>,
  ): Promise<AssessmentResult> {
    return request(`/learners/${learnerId}/assessments`, {
      method: "POST",
      body: JSON.stringify({ phase: "post", answers }),
    });
  },

  resourceDownloadUrl(resourceId: string): string {
    return `${API_BASE}/resources/${resourceId}/download`;
  },
};

export const knowledgeApi = {
  getOverview(): Promise<KnowledgeOverview> {
    return request("/knowledge/overview");
  },

  async listCourses(): Promise<Course[]> {
    const payload = await request<
      KnowledgeList<Course> & { courses?: Course[] }
    >("/courses");
    return payload.items ?? payload.courses ?? [];
  },

  createCourse(input: CourseInput): Promise<Course> {
    return request("/courses", {
      method: "POST",
      body: JSON.stringify({
        title: input.title,
        description: input.description ?? "",
        color: input.color ?? "#e25d3f",
      }),
    });
  },

  updateCourse(courseId: string, input: CourseInput): Promise<Course> {
    return request(`/courses/${encodeURIComponent(courseId)}`, {
      method: "PATCH",
      body: JSON.stringify(input),
    });
  },

  deleteCourse(courseId: string): Promise<void> {
    return emptyRequest(`/courses/${encodeURIComponent(courseId)}`);
  },

  async listAssets(courseId: string): Promise<KnowledgeAsset[]> {
    const payload = await request<
      KnowledgeList<KnowledgeAsset> & { assets?: KnowledgeAsset[] }
    >(
      `/courses/${encodeURIComponent(courseId)}/assets`,
    );
    return payload.items ?? payload.assets ?? [];
  },

  uploadAsset(
    courseId: string,
    file: File,
    options: { title?: string; tags?: string[] } = {},
  ): Promise<AssetDetail> {
    const body = new FormData();
    body.append("file", file);
    if (options.title?.trim()) body.append("title", options.title.trim());
    if (options.tags?.length) body.append("tags", options.tags.join(","));
    return formRequest(`/courses/${encodeURIComponent(courseId)}/assets`, body);
  },

  createNote(
    courseId: string,
    note: { title: string; content: string; tags?: string[] },
  ): Promise<AssetDetail> {
    return request(`/courses/${encodeURIComponent(courseId)}/notes`, {
      method: "POST",
      body: JSON.stringify({
        title: note.title,
        content: note.content,
        tags: note.tags ?? [],
      }),
    });
  },

  getAsset(assetId: string): Promise<AssetDetail> {
    return request(`/assets/${encodeURIComponent(assetId)}`);
  },

  deleteAsset(assetId: string): Promise<void> {
    return emptyRequest(`/assets/${encodeURIComponent(assetId)}`);
  },

  async search(
    query: string,
    tag?: string,
    courseId?: string,
  ): Promise<KnowledgeChunk[]> {
    const params = new URLSearchParams();
    if (query.trim()) params.set("q", query.trim());
    if (tag?.trim()) params.set("tag", tag.trim());
    if (courseId?.trim()) params.set("courseId", courseId.trim());
    const suffix = params.size ? `?${params.toString()}` : "";
    const payload = await request<
      KnowledgeSearchResult & { results?: KnowledgeChunk[] }
    >(
      `/knowledge/search${suffix}`,
    );
    return payload.items ?? payload.results ?? [];
  },

  assetFileUrl(assetId: string): string {
    return `${API_BASE}/assets/${encodeURIComponent(assetId)}/file`;
  },
};

export const learningConnectorApi = {
  status(): Promise<LearningConnectorStatus> {
    return request("/learning/chaoxing/status");
  },

  startLogin(): Promise<LearningLogin> {
    return request("/learning/chaoxing/login", { method: "POST" });
  },

  pollLogin(loginId: string): Promise<LearningLoginResult> {
    return request(`/learning/chaoxing/login/${encodeURIComponent(loginId)}`);
  },

  refreshLogin(loginId: string): Promise<LearningLogin> {
    return request(
      `/learning/chaoxing/login/${encodeURIComponent(loginId)}/refresh`,
      { method: "POST" },
    );
  },

  cancelLogin(loginId: string): Promise<void> {
    return emptyRequest(
      `/learning/chaoxing/login/${encodeURIComponent(loginId)}`,
    );
  },

  qrUrl(loginId: string, revision: number): string {
    return `${API_BASE}/learning/chaoxing/login/${encodeURIComponent(loginId)}/qr?revision=${revision}`;
  },

  createPreview(): Promise<LearningImportPreview> {
    return request("/learning/chaoxing/previews", { method: "POST" });
  },

  loadCourseDocuments(
    previewId: string,
    courseId: string,
  ): Promise<LearningImportPreview> {
    return request(
      `/learning/chaoxing/previews/${encodeURIComponent(previewId)}` +
        `/courses/${encodeURIComponent(courseId)}/documents`,
      { method: "POST" },
    );
  },

  previewZip(file: File): Promise<LearningImportPreview> {
    const body = new FormData();
    body.append("file", file);
    return formRequest("/learning/imports/zip/previews", body);
  },

  createImport(
    previewId: string,
    mappings: LearningFolderMapping[],
  ): Promise<LearningImportJob> {
    return request("/learning/imports", {
      method: "POST",
      body: JSON.stringify({ previewId, mappings }),
    });
  },

  getImport(jobId: string): Promise<LearningImportDetail> {
    return request(`/learning/imports/${encodeURIComponent(jobId)}`);
  },

  cancelImport(jobId: string): Promise<LearningImportJob> {
    return request(
      `/learning/imports/${encodeURIComponent(jobId)}/cancel`,
      { method: "POST" },
    );
  },

  retryImport(jobId: string): Promise<LearningImportJob> {
    return request(
      `/learning/imports/${encodeURIComponent(jobId)}/retry`,
      { method: "POST" },
    );
  },

  disconnect(): Promise<void> {
    return emptyRequest("/learning/chaoxing/connection");
  },
};
