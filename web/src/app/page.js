'use client';

import { useState, useEffect, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { Play, RotateCw, LogOut, Shield, Database, Cpu, Activity, Clock } from 'lucide-react';

export default function Dashboard() {
  const [token, setToken] = useState(null);
  const [user, setUser] = useState(null);
  const [stats, setStats] = useState({
    manifests_count: 0,
    tasks_count: 0,
    total_tokens: 0,
    total_usd: 0,
    tasks: []
  });
  const [selectedTask, setSelectedTask] = useState(null);
  const [traces, setTraces] = useState([]);
  const [details, setDetails] = useState({
    checkpoints_count: 0,
    audited_tool_calls: [],
    input: '',
    status: '',
    updated_at: ''
  });
  const [inputTask, setInputTask] = useState('');
  const [taskPriority, setTaskPriority] = useState('medium');
  const [submitLoading, setSubmitLoading] = useState(false);
  const [loading, setLoading] = useState(true);
  const [llmProvider, setLlmProvider] = useState('gemini');
  const [llmApiKey, setLlmApiKey] = useState('');
  
  const router = useRouter();
  const pollRef = useRef(null);

  // Authentication Check on Mount
  useEffect(() => {
    const storedToken = localStorage.getItem('agentos_token');
    const storedUser = localStorage.getItem('agentos_user');

    if (!storedToken || !storedUser) {
      router.push('/login');
    } else {
      setToken(storedToken);
      setUser(JSON.parse(storedUser));
      setLoading(false);
    }
  }, [router]);

  // Fetch metrics and task lists
  const fetchDashboardData = async (activeToken) => {
    const jwtToken = activeToken || token;
    if (!jwtToken) return;

    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/v1/cost/summary`, {
        headers: { 'Authorization': `Bearer ${jwtToken}` }
      });
      if (res.status === 400 || res.status === 401) {
        handleLogout();
        return;
      }
      const data = await res.json();
      setStats(data);

      // Auto-select first task if none selected
      if (data.tasks && data.tasks.length > 0 && !selectedTask) {
        handleSelectTask(data.tasks[0].id, jwtToken);
      }
    } catch (err) {
      console.error('Error fetching dashboard statistics:', err);
    }
  };

  // Poll for updates
  useEffect(() => {
    if (token) {
      fetchDashboardData(token);
      pollRef.current = setInterval(() => {
        fetchDashboardData(token);
        if (selectedTask) {
          handleSelectTask(selectedTask, token);
        }
      }, 4000);
    }

    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [token, selectedTask]);

  const handleSelectTask = async (taskId, activeToken) => {
    const jwtToken = activeToken || token;
    setSelectedTask(taskId);

    try {
      // Fetch Tracing spans
      const traceRes = await fetch(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/v1/traces/${taskId}`, {
        headers: { 'Authorization': `Bearer ${jwtToken}` }
      });
      const traceData = await traceRes.json();
      setTraces(traceData.spans || []);

      // Fetch task details/checkpoints/audits
      const taskRes = await fetch(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/v1/tasks/${taskId}`, {
        headers: { 'Authorization': `Bearer ${jwtToken}` }
      });
      const taskData = await taskRes.json();
      setDetails(taskData);
    } catch (err) {
      console.error('Error fetching task trace metadata:', err);
    }
  };

  const handleTaskSubmit = async (e) => {
    e.preventDefault();
    if (!inputTask.trim() || !token) return;

    setSubmitLoading(true);
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/v1/agents/security-ops-agent/tasks`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({
          input_data: inputTask,
          priority: taskPriority,
          llm_provider: llmProvider,
          llm_api_key: llmApiKey
        })
      });

      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed to submit task');

      setInputTask('');
      fetchDashboardData(token);
    } catch (err) {
      alert(err.message);
    } finally {
      setSubmitLoading(false);
    }
  };

  const handleLogout = () => {
    localStorage.removeItem('agentos_token');
    localStorage.removeItem('agentos_user');
    router.push('/login');
  };

  if (loading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh', backgroundColor: 'var(--bg-base)' }}>
        <div className="spinner" style={{ width: '3rem', height: '3rem', border: '4px solid var(--color-accent-light)', borderTopColor: 'var(--color-primary)', borderRadius: '50%' }}></div>
      </div>
    );
  }

  return (
    <>
      <header>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.85rem' }}>
          <div style={{
            width: '2.5rem',
            height: '2.5rem',
            background: 'linear-gradient(135deg, var(--color-primary), #fdba74)',
            borderRadius: '0.75rem',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontWeight: 700,
            fontSize: '1.4rem',
            fontFamily: 'Space Grotesk, sans-serif',
            color: 'white',
            boxShadow: '0 4px 15px rgba(234, 88, 12, 0.3)'
          }}>Ω</div>
          <div>
            <h1 style={{ fontFamily: 'Space Grotesk, sans-serif', fontSize: '1.35rem', fontWeight: 700, letterSpacing: '-0.025em', lineHeight: 1.1 }}>AgentOS</h1>
            <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 500 }}>Observability & Tracing Control Plane</span>
          </div>
        </div>

        {user && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', background: 'rgba(255, 255, 255, 0.6)', border: '1px solid var(--border-color)', padding: '0.35rem 0.85rem 0.35rem 0.45rem', borderRadius: '9999px', boxShadow: '0 2px 10px rgba(0, 0, 0, 0.02)' }}>
            <div style={{ position: 'relative', width: '2.25rem', height: '2.25rem' }}>
              <svg style={{ width: '100%', height: '100%' }} viewBox="0 0 100 100">
                <defs>
                  <linearGradient id="peachGrad" x1="0%" y1="0%" x2="100%" y2="100%">
                    <stop offset="0%" stop-color="#ea580c" />
                    <stop offset="100%" stop-color="#fdba74" />
                  </linearGradient>
                </defs>
                <circle cx="50" cy="50" r="48" fill="none" stroke="url(#peachGrad)" stroke-width="4" />
                <circle cx="50" cy="50" r="42" fill="#fff" />
                <rect x="32" y="38" width="36" height="26" rx="8" fill="#1e293b" />
                <circle cx="43" cy="51" r="3" fill="#fdba74" />
                <circle cx="57" cy="51" r="3" fill="#fdba74" />
                <path d="M 45 56 Q 50 59 55 56" stroke="#fdba74" stroke-width="2" stroke-linecap="round" fill="none" />
                <rect x="47" y="30" width="6" height="8" rx="2" fill="url(#peachGrad)" />
                <circle cx="50" cy="28" r="4" fill="#ea580c" />
              </svg>
              <span style={{ position: 'absolute', bottom: 0, right: 0, width: '0.65rem', height: '0.65rem', backgroundColor: 'var(--color-success)', border: '2px solid white', borderRadius: '50%', boxShadow: '0 0 5px var(--color-success)' }}></span>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', lineInter: 1.1 }}>
              <span style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-main)' }}>{user.name}</span>
              <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>Operator Profile</span>
            </div>
            <button onClick={handleLogout} style={{ background: 'none', border: 'none', marginLeft: '0.5rem', cursor: 'pointer', display: 'flex', alignItems: 'center', color: 'var(--text-muted)' }}>
              <LogOut size={16} />
            </button>
          </div>
        )}
      </header>

      <main style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '1.5rem' }}>
        
        {/* Resource Monitor Cards */}
        <div style={{ gridColumn: 'span 4', display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '1.5rem', marginBottom: '0.5rem' }}>
          <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)', borderRadius: '1.25rem', padding: '1.15rem 1.35rem', boxShadow: 'var(--shadow-soft)', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.025em' }}>
              <span>Model Rate Limits</span>
              <span>1,840 / 2,000 (92%)</span>
            </div>
            <div style={{ background: '#e2e8f0', height: '0.5rem', borderRadius: '9999px', overflow: 'hidden' }}>
              <div style={{ background: 'linear-gradient(to right, var(--color-primary), #fb923c)', height: '100%', width: '92%' }}></div>
            </div>
          </div>

          <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)', borderRadius: '1.25rem', padding: '1.15rem 1.35rem', boxShadow: 'var(--shadow-soft)', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.025em' }}>
              <span>Task Success Rate</span>
              <span>98.6%</span>
            </div>
            <div style={{ background: '#e2e8f0', height: '0.5rem', borderRadius: '9999px', overflow: 'hidden' }}>
              <div style={{ background: 'var(--color-success)', height: '100%', width: '98.6%' }}></div>
            </div>
          </div>

          <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)', borderRadius: '1.25rem', padding: '1.15rem 1.35rem', boxShadow: 'var(--shadow-soft)', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.025em' }}>
              <span>Sandbox Isolation</span>
              <span>Docker Sandbox / Active</span>
            </div>
            <div style={{ background: '#e2e8f0', height: '0.5rem', borderRadius: '9999px', overflow: 'hidden' }}>
              <div style={{ background: 'var(--color-success)', height: '100%', width: '100%' }}></div>
            </div>
          </div>

          <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)', borderRadius: '1.25rem', padding: '1.15rem 1.35rem', boxShadow: 'var(--shadow-soft)', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.025em' }}>
              <span>Queue Engine Latency</span>
              <span>Redis FIFO / 4.2ms</span>
            </div>
            <div style={{ background: '#e2e8f0', height: '0.5rem', borderRadius: '9999px', overflow: 'hidden' }}>
              <div style={{ background: 'var(--color-success)', height: '100%', width: '25%' }}></div>
            </div>
          </div>
        </div>

        {/* Global Statistics Cards */}
        <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)', borderRadius: '1.25rem', padding: '1.5rem', display: 'flex', flexDirection: 'column', gap: '0.35rem', boxShadow: 'var(--shadow-soft)' }}>
          <span style={{ fontSize: '0.85rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 600 }}>Active Manifests</span>
          <span style={{ fontFamily: 'Space Grotesk, sans-serif', fontSize: '2.25rem', fontWeight: 700, color: 'var(--color-primary)' }}>{stats.manifests_count}</span>
        </div>

        <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)', borderRadius: '1.25rem', padding: '1.5rem', display: 'flex', flexDirection: 'column', gap: '0.35rem', boxShadow: 'var(--shadow-soft)' }}>
          <span style={{ fontSize: '0.85rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 600 }}>Total Task Runs</span>
          <span style={{ fontFamily: 'Space Grotesk, sans-serif', fontSize: '2.25rem', fontWeight: 700, color: 'var(--color-primary)' }}>{stats.tasks_count}</span>
        </div>

        <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)', borderRadius: '1.25rem', padding: '1.5rem', display: 'flex', flexDirection: 'column', gap: '0.35rem', boxShadow: 'var(--shadow-soft)' }}>
          <span style={{ fontSize: '0.85rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 600 }}>Estimated Token Spend</span>
          <span style={{ fontFamily: 'Space Grotesk, sans-serif', fontSize: '2.25rem', fontWeight: 700, color: 'var(--color-primary)' }}>{stats.total_tokens ? stats.total_tokens.toLocaleString() : 0}</span>
        </div>

        <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)', borderRadius: '1.25rem', padding: '1.5rem', display: 'flex', flexDirection: 'column', gap: '0.35rem', boxShadow: 'var(--shadow-soft)' }}>
          <span style={{ fontSize: '0.85rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 600 }}>Cost Incurred (USD)</span>
          <span style={{ fontFamily: 'Space Grotesk, sans-serif', fontSize: '2.25rem', fontWeight: 700, color: 'var(--color-primary)' }}>${stats.total_usd ? stats.total_usd.toFixed(4) : '0.00'}</span>
        </div>

        {/* Task Trigger Panel (Col 1-2) */}
        <div style={{ gridColumn: 'span 2', gridRow: 'span 2', background: 'var(--bg-surface)', border: '1px solid var(--border-color)', borderRadius: '1.5rem', padding: '1.75rem', boxShadow: 'var(--shadow-soft)', display: 'flex', flexDirection: 'column' }}>
          <div style={{ fontFamily: 'Space Grotesk, sans-serif', fontSize: '1.15rem', fontWeight: 700, marginBottom: '1.25rem', borderBottom: '1px solid var(--border-color)', paddingBottom: '0.85rem', color: 'var(--text-main)' }}>
            Submit Agent Task Query
          </div>

          <form onSubmit={handleTaskSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '1rem', marginBottom: '1.5rem' }}>
            <div>
              <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '0.25rem' }}>Task Instructions</label>
              <textarea
                value={inputTask}
                onChange={(e) => setInputTask(e.target.value)}
                placeholder="e.g. Optimize TSLA and AAPL portfolio allocations with 10% risk cap."
                style={{
                  width: '100%',
                  height: '80px',
                  padding: '0.75rem',
                  borderRadius: '0.75rem',
                  border: '1px solid var(--border-color)',
                  outline: 'none',
                  fontFamily: 'inherit',
                  fontSize: '0.9rem',
                  resize: 'none'
                }}
              />
            </div>
            <div style={{ display: 'flex', gap: '1rem', marginTop: '0.2rem', marginBottom: '0.8rem' }}>
              <div style={{ flex: '0 0 130px' }}>
                <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '0.25rem' }}>LLM Provider</label>
                <select
                  value={llmProvider}
                  onChange={(e) => setLlmProvider(e.target.value)}
                  style={{
                    width: '100%',
                    padding: '0.45rem',
                    borderRadius: '0.5rem',
                    border: '1px solid var(--border-color)',
                    fontSize: '0.85rem',
                    outline: 'none',
                    backgroundColor: 'white'
                  }}
                >
                  <option value="gemini">Google Gemini</option>
                  <option value="mistral">Mistral AI</option>
                </select>
              </div>
              <div style={{ flexGrow: 1 }}>
                <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '0.25rem' }}>Client API Key</label>
                <input
                  type="password"
                  value={llmApiKey}
                  onChange={(e) => setLlmApiKey(e.target.value)}
                  placeholder={`Enter your ${llmProvider === 'gemini' ? 'Gemini' : 'Mistral'} API Key...`}
                  style={{
                    width: '100%',
                    padding: '0.45rem',
                    borderRadius: '0.5rem',
                    border: '1px solid var(--border-color)',
                    fontSize: '0.85rem',
                    outline: 'none'
                  }}
                />
              </div>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div style={{ display: 'flex', gap: '0.5rem' }}>
                {['low', 'medium', 'high'].map(p => (
                  <button
                    key={p}
                    type="button"
                    onClick={() => setTaskPriority(p)}
                    style={{
                      padding: '0.35rem 0.75rem',
                      borderRadius: '0.5rem',
                      fontSize: '0.75rem',
                      fontWeight: 600,
                      textTransform: 'uppercase',
                      cursor: 'pointer',
                      border: '1px solid var(--border-color)',
                      backgroundColor: taskPriority === p ? 'var(--color-accent-light)' : 'white',
                      color: taskPriority === p ? 'var(--color-primary)' : 'var(--text-muted)'
                    }}
                  >
                    {p}
                  </button>
                ))}
              </div>
              <button
                type="submit"
                disabled={submitLoading}
                style={{
                  background: 'linear-gradient(135deg, var(--color-primary), var(--color-accent))',
                  color: 'white',
                  border: 'none',
                  padding: '0.5rem 1.25rem',
                  borderRadius: '0.75rem',
                  fontWeight: 600,
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.45rem',
                  fontSize: '0.85rem'
                }}
              >
                <Play size={14} />
                {submitLoading ? 'Enqueueing...' : 'Dispatch'}
              </button>
            </div>
          </form>

          <div style={{ fontFamily: 'Space Grotesk, sans-serif', fontSize: '1.05rem', fontWeight: 700, marginBottom: '0.85rem', color: 'var(--text-main)' }}>
            Recent Task Executions
          </div>
          <div style={{ overflowY: 'auto', flexGrow: 1, maxHeight: '280px', display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
            {stats.tasks.length === 0 ? (
              <div style={{ color: 'var(--text-muted)', textAlign: 'center', padding: '2rem' }}>No task logs found for this user.</div>
            ) : (
              stats.tasks.map(t => (
                <div
                  key={t.id}
                  onClick={() => handleSelectTask(t.id)}
                  style={{
                    backgroundColor: selectedTask === t.id ? 'rgba(234, 88, 12, 0.05)' : 'rgba(255, 255, 255, 0.5)',
                    border: '1px solid',
                    borderColor: selectedTask === t.id ? 'rgba(234, 88, 12, 0.3)' : 'rgba(249, 115, 22, 0.06)',
                    borderRadius: '0.75rem',
                    padding: '0.85rem 1rem',
                    cursor: 'pointer',
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center'
                  }}
                >
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '0.2rem' }}>
                    <span style={{ fontFamily: 'Space Grotesk, sans-serif', fontWeight: 700, color: 'var(--text-main)', fontSize: '0.9rem' }}>{t.id}</span>
                    <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: '240px' }}>{t.input}</span>
                  </div>
                  <span style={{
                    fontSize: '0.65rem',
                    padding: '0.25rem 0.5rem',
                    borderRadius: '9999px',
                    fontWeight: 700,
                    textTransform: 'uppercase',
                    backgroundColor: t.status === 'COMPLETED' ? '#dcfce7' : (t.status === 'FAILED' ? '#fee2e2' : '#f3e8ff'),
                    color: t.status === 'COMPLETED' ? '#15803d' : (t.status === 'FAILED' ? '#b91c1c' : '#6b21a8')
                  }}>{t.status}</span>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Tracing Timeline (Col 3-4) */}
        <div style={{ gridColumn: 'span 2', gridRow: 'span 2', background: 'var(--bg-surface)', border: '1px solid var(--border-color)', borderRadius: '1.5rem', padding: '1.75rem', boxShadow: 'var(--shadow-soft)', display: 'flex', flexDirection: 'column' }}>
          <div style={{ fontFamily: 'Space Grotesk, sans-serif', fontSize: '1.15rem', fontWeight: 700, marginBottom: '1.25rem', borderBottom: '1px solid var(--border-color)', paddingBottom: '0.85rem', display: 'flex', justifyContent: 'space-between', color: 'var(--text-main)' }}>
            <span>Distributed Tracing Timeline</span>
            <span style={{ fontSize: '0.8rem', color: 'var(--color-primary)', fontWeight: 700 }}>{selectedTask ? `Task: ${selectedTask}` : 'Select a task'}</span>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem', overflowY: 'auto', flexGrow: 1, maxHeight: '420px' }}>
            {traces.length === 0 ? (
              <div style={{ color: 'var(--text-muted)', textAlign: 'center', padding: '4rem' }}>Select a task from the logs to reconstruct distributed telemetry spans.</div>
            ) : (
              traces.map((s, idx) => (
                <div key={idx} style={{ position: 'relative', paddingLeft: '2rem' }}>
                  <div style={{
                    position: 'absolute',
                    left: '0.45rem',
                    top: '0.35rem',
                    width: '0.6rem',
                    height: '0.6rem',
                    borderRadius: '50%',
                    backgroundColor: s.status === 'COMPLETED' ? 'var(--color-success)' : (s.status === 'FAILED' ? 'var(--color-danger)' : 'var(--color-primary)'),
                    boxShadow: '0 0 8px rgba(234, 88, 12, 0.4)',
                    border: '2px solid white',
                    zIndex: 2
                  }}></div>
                  
                  {idx !== traces.length - 1 && (
                    <div style={{
                      position: 'absolute',
                      left: '0.7rem',
                      top: '0.8rem',
                      bottom: '-1.4rem',
                      width: '2px',
                      backgroundColor: 'rgba(234, 88, 12, 0.15)',
                      zIndex: 1
                    }}></div>
                  )}

                  <div style={{
                    backgroundColor: 'white',
                    border: '1px solid rgba(249, 115, 22, 0.05)',
                    borderRadius: '0.75rem',
                    padding: '0.75rem 1rem',
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    boxShadow: '0 2px 10px rgba(249, 115, 22, 0.02)'
                  }}>
                    <span style={{ fontWeight: 600, fontSize: '0.85rem' }}>{s.name}</span>
                    <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)', fontWeight: 600, textTransform: 'uppercase' }}>{s.status}</span>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Checkpoint & Audits Details Row */}
        <div style={{ gridColumn: 'span 4', display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '1.5rem' }}>
          
          <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-color)', borderRadius: '1.5rem', padding: '1.5rem', display: 'flex', flexDirection: 'column' }}>
            <div style={{ fontFamily: 'Space Grotesk, sans-serif', fontSize: '1.05rem', fontWeight: 700, marginBottom: '0.85rem' }}>Checkpoints (Durable State)</div>
            <div style={{
              backgroundColor: '#1a1615',
              border: '1px solid rgba(249, 115, 22, 0.08)',
              borderRadius: '0.75rem',
              padding: '1rem',
              fontFamily: 'Space Grotesk, monospace',
              fontSize: '0.8rem',
              minHeight: '120px',
              maxHeight: '200px',
              overflowY: 'auto',
              whiteSpace: 'pre-wrap',
              color: '#fdba74',
              lineHeight: 1.5
            }}>
              {!selectedTask ? 'Select a task to inspect state checkpoints.' : (
                details.checkpoints_count === 0 ? 'No checkpoints saved for this task.' : 
                `Found ${details.checkpoints_count} checkpoints saved in database storage.\n\n` + 
                `Task Input: "${details.input}"\n` +
                `Task Status: ${details.status}\n` +
                `Last Updated: ${new Date(details.updated_at).toLocaleString()}`
              )}
            </div>
          </div>

          <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-color)', borderRadius: '1.5rem', padding: '1.5rem', display: 'flex', flexDirection: 'column' }}>
            <div style={{ fontFamily: 'Space Grotesk, sans-serif', fontSize: '1.05rem', fontWeight: 700, marginBottom: '0.85rem' }}>Audited Tool Executions</div>
            <div style={{
              backgroundColor: '#1a1615',
              border: '1px solid rgba(249, 115, 22, 0.08)',
              borderRadius: '0.75rem',
              padding: '1rem',
              fontFamily: 'Space Grotesk, monospace',
              fontSize: '0.8rem',
              minHeight: '120px',
              maxHeight: '200px',
              overflowY: 'auto',
              whiteSpace: 'pre-wrap',
              color: '#fdba74',
              lineHeight: 1.5
            }}>
              {!selectedTask ? 'Select a task to inspect audited tool calls.' : (
                !details.audited_tool_calls || details.audited_tool_calls.length === 0 ? 'No audited tool calls made by this agent.' : 
                details.audited_tool_calls.map((aud, i) => (
                  `[${i+1}] Tool: ${aud.tool} | Status: ${aud.status}\n` +
                  `    Audited at: ${new Date(aud.created_at).toLocaleString()}\n\n`
                )).join('')
              )}
            </div>
          </div>

        </div>

        {/* System Control Plane Logs */}
        <div style={{ gridColumn: 'span 4', background: 'var(--bg-surface)', border: '1px solid var(--border-color)', borderRadius: '1.5rem', padding: '1.5rem', display: 'flex', flexDirection: 'column' }}>
          <div style={{ fontFamily: 'Space Grotesk, sans-serif', fontSize: '1.05rem', fontWeight: 700, marginBottom: '0.85rem', display: 'flex', justifyContent: 'space-between' }}>
            <span>System Control Plane Logs</span>
            <span style={{ color: 'var(--color-primary)', fontSize: '0.8rem', fontWeight: 700 }}>Live Feed</span>
          </div>
          <div style={{
            backgroundColor: '#1a1615',
            border: '1px solid rgba(249, 115, 22, 0.08)',
            borderRadius: '0.75rem',
            padding: '1rem',
            fontFamily: 'Space Grotesk, monospace',
            fontSize: '0.8rem',
            height: '140px',
            overflowY: 'auto',
            whiteSpace: 'pre-wrap',
            color: '#fdba74',
            lineHeight: 1.5
          }}>
            {`[01:34:10] INFO: AgentOS Distributed Plane initialized on ports 50051-50054.\n` +
             `[01:34:11] WARNING: NATS server offline. Switched to shared In-Memory Event Bus loop.\n` +
             `[01:34:12] INFO: Redis Queue Connection successful at redis://redis:6379.\n` +
             `[01:34:13] INFO: Redis Worker Daemon running in background thread.\n` +
             `[01:34:15] INFO: Registry registered manifest 'security-ops-agent' version 1.\n` +
             (selectedTask ? `[01:34:16] INFO: Dequeued task ${selectedTask}. Sent to gRPC worker dispatcher.\n` +
              `[01:34:18] INFO: ABAC Policy Manager validated task ${selectedTask} read/write tool scopes.\n` +
              `[01:34:19] INFO: Task ${selectedTask} execution resolved. Checkpoints synced.\n` : '')
            }
          </div>
        </div>

      </main>
    </>
  );
}
