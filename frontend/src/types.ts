export interface ProfileDimension {
  value: string;
  evidence: string;
  confidence: number;
  updated_at: string;
}

export interface LearnerProfile {
  dimensions: Record<string, ProfileDimension>;
  mastery: Record<string, number>;
}

export interface Persona {
  id: string;
  name: string;
  label: string;
  summary: string;
  profile: LearnerProfile;
}

export interface Learner {
  id: string;
  name: string;
  course_id: string;
  persona_id: string | null;
  profile: LearnerProfile;
}

export interface ProfileUpdate {
  profile: LearnerProfile;
  assistant_message: string;
  changed_dimensions: string[];
}

export interface AgentEvent {
  sequence: number;
  run_id: string;
  agent: string;
  phase: string;
  status: string;
  summary: string;
  data: {
    resource?: LearningResource;
    error?: string;
  };
  created_at: string;
}

export interface LearningResource {
  id: string | null;
  type: string;
  title: string;
  knowledge_point: string;
  content: Record<string, unknown>;
  metadata: Record<string, unknown>;
  status: string;
}

export interface RunSnapshot {
  id: string;
  learner_id: string;
  topic: string;
  status: string;
  progress: number;
  events: AgentEvent[];
  resources: LearningResource[];
}

export interface TutorSource {
  title: string;
  module: string;
  knowledge_point: string;
  path: string;
}

export interface TutorAnswer {
  text: string;
  sources: TutorSource[];
  refused: boolean;
  refusal_reason: string | null;
}

export interface AssessmentQuestion {
  id: string;
  stem: string;
  options: string[];
  knowledge_point: string;
  explanation: string;
}

export interface AssessmentResult {
  score: number;
  correct_count: number;
  total: number;
  mastery: Record<string, number>;
  updated_profile: LearnerProfile;
  recommendation: string;
}

export interface PathNode {
  id: string;
  title: string;
  topic: string;
  status: string;
  dependency: string | null;
  recommendation: string;
  resource_types: string[];
}

export interface LearningPath {
  id: string;
  learner_id: string;
  title: string;
  nodes: PathNode[];
  adjustment_note: string;
}

export interface AuthUser {
  id: string;
  name: string;
  email: string;
}

export interface AuthWorkspace {
  id: string;
  name: string;
  role: string;
}

export interface AuthContext {
  user: AuthUser;
  workspace: AuthWorkspace;
}

export interface Course {
  id: string;
  title: string;
  description: string;
  color: string;
  assetCount: number;
  knowledgeCount: number;
  updatedAt: string;
}

export interface CourseInput {
  title: string;
  description?: string;
  color?: string;
}

export type KnowledgeAssetKind = "file" | "image" | "note";
export type KnowledgeAssetStatus =
  | "processing"
  | "ready"
  | "ready_image_only"
  | "failed";

export interface KnowledgeAsset {
  id: string;
  courseId: string;
  courseTitle: string;
  kind: KnowledgeAssetKind;
  title: string;
  originalName: string | null;
  mimeType: string | null;
  status: KnowledgeAssetStatus;
  summary: string;
  content: string;
  tags: string[];
  knowledgeCount: number;
  sizeBytes?: number;
  error: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface KnowledgeChunk {
  id: string;
  assetId: string;
  assetTitle: string;
  courseId: string;
  courseTitle: string;
  title: string;
  excerpt: string;
  tags: string[];
}

export interface AssetDetail extends KnowledgeAsset {
  chunks: KnowledgeChunk[];
  fileAvailable: boolean;
}

export interface KnowledgeOverview {
  courseCount: number;
  assetCount: number;
  knowledgeCount: number;
  pendingCount: number;
  recentAssets: KnowledgeAsset[];
  courses: Course[];
  topTags: string[];
}

export interface KnowledgeList<T> {
  items: T[];
}

export interface KnowledgeSearchResult {
  items: KnowledgeChunk[];
  total?: number;
}

export type LearningConnectionStatus =
  | "pending"
  | "connected"
  | "expired"
  | "error"
  | "revoked";

export interface LearningConnection {
  id: string;
  provider: "chaoxing";
  remoteNickname: string | null;
  status: LearningConnectionStatus;
  expiresAt: string | null;
  lastSyncedAt: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface LearningConnectorStatus {
  enabled: boolean;
  connection: LearningConnection | null;
}

export interface LearningLogin {
  id: string;
  status: "pending" | "confirming";
  expiresAt: string;
  revision: number;
  message?: string | null;
}

export type LearningLoginResultStatus =
  | "pending"
  | "confirming"
  | "connected"
  | "cancelled"
  | "expired"
  | "verification_required";

export interface LearningLoginResult {
  status: LearningLoginResultStatus;
  remoteNickname: string | null;
  message: string | null;
}

export interface LearningPreviewFile {
  id: string;
  name: string;
  extension: string;
  sizeBytes: number;
  supported: boolean;
  excludedReason: string | null;
}

export interface LearningPreviewCourse {
  id: string;
  title: string;
  teacher: string;
  documents: LearningPreviewFile[];
  videoLinks: string[];
}

export interface LearningImportPreview {
  id: string;
  courses: LearningPreviewCourse[];
  totalDocuments: number;
  totalVideoLinks: number;
  totalBytes: number;
  generatedAt: string;
  expiresAt: string;
}

export interface LearningFolderMapping {
  previewCourseId: string;
  mode: "new" | "merge" | "skip";
  targetCourseId?: string | null;
  folderTitle?: string | null;
}

export type LearningJobStatus =
  | "queued"
  | "reading"
  | "downloading"
  | "parsing"
  | "completed"
  | "partial_failed"
  | "cancelled"
  | "session_expired";

export interface LearningImportItem {
  id: string;
  jobId: string;
  kind: "file" | "video_links" | "zip_file";
  title: string;
  externalCourseId: string;
  externalFileId: string | null;
  targetCourseId: string;
  status: "queued" | "downloading" | "parsing" | "completed" | "skipped" | "failed";
  attempts: number;
  checksum: string | null;
  assetId: string | null;
  errorCode: string | null;
  errorMessage: string | null;
  sizeBytes: number;
  createdAt: string;
  updatedAt: string;
}

export interface LearningImportJob {
  id: string;
  previewId: string;
  status: LearningJobStatus;
  progress: number;
  totalItems: number;
  completedItems: number;
  failedItems: number;
  skippedItems: number;
  cancelRequested: boolean;
  createdAt: string;
  startedAt: string | null;
  finishedAt: string | null;
  errorCode: string | null;
  errorMessage: string | null;
}

export interface LearningImportDetail {
  job: LearningImportJob;
  items: LearningImportItem[];
}
