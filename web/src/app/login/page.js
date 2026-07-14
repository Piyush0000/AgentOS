'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';

export default function Login() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const router = useRouter();

  const handleLogin = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/v1/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password })
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.error || 'Failed to authenticate');
      }

      localStorage.setItem('agentos_token', data.token);
      localStorage.setItem('agentos_user', JSON.stringify(data.user));
      
      router.push('/');
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      minHeight: '100vh',
      padding: '1rem',
      backgroundColor: 'var(--bg-base)'
    }}>
      <div style={{
        background: 'var(--bg-card)',
        backdropFilter: 'blur(16px)',
        border: '1px solid var(--border-color)',
        borderRadius: '1.5rem',
        padding: '2.5rem',
        width: '100%',
        maxWidth: '440px',
        boxShadow: 'var(--shadow-soft)'
      }}>
        <div style={{ textAlign: 'center', marginBottom: '2rem' }}>
          <div style={{
            width: '3.5rem',
            height: '3.5rem',
            background: 'linear-gradient(135deg, var(--color-primary), #fdba74)',
            borderRadius: '1rem',
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontWeight: '700',
            fontSize: '1.8rem',
            fontFamily: 'Space Grotesk, sans-serif',
            color: 'white',
            marginBottom: '1rem',
            boxShadow: '0 4px 15px rgba(234, 88, 12, 0.3)'
          }}>Ω</div>
          <h2 style={{ fontFamily: 'Space Grotesk, sans-serif', fontSize: '1.75rem', fontWeight: 700 }}>AgentOS Gateway</h2>
          <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem', marginTop: '0.25rem' }}>Login to access your control plane</p>
        </div>

        {error && (
          <div style={{
            backgroundColor: '#fee2e2',
            color: '#b91c1c',
            padding: '0.75rem 1rem',
            borderRadius: '0.75rem',
            fontSize: '0.85rem',
            marginBottom: '1.5rem',
            fontWeight: 500,
            border: '1px solid rgba(220, 38, 38, 0.1)'
          }}>
            {error}
          </div>
        )}

        <form onSubmit={handleLogin} style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
          <div>
            <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-main)', marginBottom: '0.5rem' }}>Email Address</label>
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              style={{
                width: '100%',
                padding: '0.75rem 1rem',
                borderRadius: '0.75rem',
                border: '1px solid var(--border-color)',
                outline: 'none',
                fontFamily: 'inherit',
                fontSize: '0.925rem'
              }}
              placeholder="operator@agentos.io"
            />
          </div>

          <div>
            <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-main)', marginBottom: '0.5rem' }}>Security Password</label>
            <input
              type="password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              style={{
                width: '100%',
                padding: '0.75rem 1rem',
                borderRadius: '0.75rem',
                border: '1px solid var(--border-color)',
                outline: 'none',
                fontFamily: 'inherit',
                fontSize: '0.925rem'
              }}
              placeholder="••••••••"
            />
          </div>

          <button
            type="submit"
            disabled={loading}
            style={{
              background: 'linear-gradient(135deg, var(--color-primary), var(--color-accent))',
              color: 'white',
              border: 'none',
              padding: '0.85rem',
              borderRadius: '0.75rem',
              fontWeight: 600,
              cursor: 'pointer',
              fontSize: '0.95rem',
              marginTop: '0.5rem',
              boxShadow: '0 4px 12px rgba(234, 88, 12, 0.2)',
              transition: 'transform 0.1s ease'
            }}
          >
            {loading ? 'Authenticating...' : 'Sign In'}
          </button>
        </form>

        <div style={{ textAlign: 'center', marginTop: '1.5rem', fontSize: '0.875rem', color: 'var(--text-muted)' }}>
          Don't have an operator profile?{' '}
          <Link href="/register" style={{ color: 'var(--color-primary)', fontWeight: 600, textDecoration: 'none' }}>
            Register Profile
          </Link>
        </div>
      </div>
    </div>
  );
}
