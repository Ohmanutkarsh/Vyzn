-- ========================================================================
-- VYZN Netra — Supabase PostgreSQL Schema Migration
-- Run this script in your Supabase project's SQL Editor (https://supabase.com/dashboard/project/_/sql)
-- ========================================================================

-- 1. Create table for VYZN Users & Login Information
CREATE TABLE IF NOT EXISTS public.vyzn_users (
    id TEXT PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    phone_e164 TEXT,
    email_verified BOOLEAN DEFAULT TRUE,
    phone_verified BOOLEAN DEFAULT FALSE,
    telegram_status TEXT DEFAULT 'not_linked',
    telegram_chat_id TEXT,
    last_sign_in_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for instant lookups by email and phone
CREATE INDEX IF NOT EXISTS idx_vyzn_users_email ON public.vyzn_users (email);
CREATE INDEX IF NOT EXISTS idx_vyzn_users_phone ON public.vyzn_users (phone_e164);

-- 2. Create table for Login Audit History
CREATE TABLE IF NOT EXISTS public.vyzn_login_history (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id TEXT REFERENCES public.vyzn_users(id) ON DELETE CASCADE,
    email TEXT NOT NULL,
    auth_method TEXT DEFAULT 'email_otp',
    ip_address TEXT,
    user_agent TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_vyzn_login_history_user ON public.vyzn_login_history (user_id);
CREATE INDEX IF NOT EXISTS idx_vyzn_login_history_email ON public.vyzn_login_history (email);

-- 3. Row Level Security (RLS) Configuration
ALTER TABLE public.vyzn_users ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.vyzn_login_history ENABLE ROW LEVEL SECURITY;

-- Allow Anon & Service Role to select and upsert user data
CREATE POLICY "Allow public anon access to vyzn_users"
    ON public.vyzn_users
    FOR ALL
    TO anon, authenticated, service_role
    USING (true)
    WITH CHECK (true);

CREATE POLICY "Allow public anon access to vyzn_login_history"
    ON public.vyzn_login_history
    FOR ALL
    TO anon, authenticated, service_role
    USING (true)
    WITH CHECK (true);

-- Enable Realtime broadcasting if needed
ALTER PUBLICATION supabase_realtime ADD TABLE public.vyzn_users;
