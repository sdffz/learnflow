import {
  AlertCircle,
  ArrowRight,
  BookOpen,
  LoaderCircle,
  Search,
  Tags,
} from "lucide-react";
import { useState, type FormEvent } from "react";

import { knowledgeApi } from "../api";
import type { KnowledgeChunk } from "../types";

interface Props {
  tags: string[];
  onOpenAsset: (assetId: string) => void;
}

export default function KnowledgePage({ tags, onOpenAsset }: Props) {
  const [query, setQuery] = useState("");
  const [selectedTag, setSelectedTag] = useState<string | null>(null);
  const [results, setResults] = useState<KnowledgeChunk[]>([]);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const search = async (nextQuery = query, nextTag = selectedTag) => {
    if (!nextQuery.trim() && !nextTag) return;
    setLoading(true);
    setError(null);
    setSearched(true);
    try {
      setResults(await knowledgeApi.search(nextQuery, nextTag ?? undefined));
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "知识检索失败",
      );
      setResults([]);
    } finally {
      setLoading(false);
    }
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    void search();
  };

  const toggleTag = (tag: string) => {
    const next = selectedTag === tag ? null : tag;
    setSelectedTag(next);
    if (query.trim() || next) void search(query, next);
  };

  return (
    <div className="page-stack knowledge-browser">
      <section className="knowledge-search-hero">
        <span className="eyebrow">PERSONAL KNOWLEDGE SEARCH</span>
        <h2>在自己的资料里找到答案</h2>
        <p>搜索文件夹名、资料标题、正文、标签或已经提取的知识片段。</p>
        <form className="knowledge-search-form" role="search" onSubmit={submit}>
          <Search size={20} />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索文件夹、资料、标签或正文"
          />
          <button className="primary-button" type="submit">
            搜索
          </button>
        </form>
      </section>

      {tags.length ? (
        <section className="knowledge-filter">
          <div>
            <Tags size={17} />
            <strong>标签筛选</strong>
          </div>
          <div>
            {tags.map((tag) => (
              <button
                key={tag}
                aria-pressed={selectedTag === tag}
                onClick={() => toggleTag(tag)}
              >
                {tag}
              </button>
            ))}
          </div>
        </section>
      ) : null}

      {loading ? (
        <div className="loading-panel">
          <LoaderCircle className="spin" size={20} />
          正在检索你的个人知识库
        </div>
      ) : null}

      {error ? (
        <div className="error-panel" role="alert">
          <AlertCircle size={18} />
          {error}
        </div>
      ) : null}

      {!loading && !error && !searched ? (
        <div className="knowledge-search-placeholder">
          <BookOpen size={28} />
          <h3>从一条关键词开始</h3>
          <p>例如“队列”“决策树”“老师强调的考点”。</p>
        </div>
      ) : null}

      {!loading && searched && !error && results.length === 0 ? (
        <div className="knowledge-search-placeholder">
          <Search size={27} />
          <h3>没有找到匹配内容，试试更短的关键词或更换标签。</h3>
        </div>
      ) : null}

      {results.length ? (
        <section className="knowledge-result-list">
          {results.map((chunk) => (
            <article key={chunk.id}>
              <div className="knowledge-result-source">
                {chunk.courseTitle} · {chunk.assetTitle}
              </div>
              <h3>{chunk.title}</h3>
              <p>{chunk.excerpt}</p>
              <div className="knowledge-result-footer">
                <div>
                  {chunk.tags.map((tag) => (
                    <span key={tag}>{tag}</span>
                  ))}
                </div>
                <button onClick={() => onOpenAsset(chunk.assetId)}>
                  打开来源
                  <ArrowRight size={15} />
                </button>
              </div>
            </article>
          ))}
        </section>
      ) : null}
    </div>
  );
}
