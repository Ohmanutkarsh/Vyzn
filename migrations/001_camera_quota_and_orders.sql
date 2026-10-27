-- ==============================================================================
-- VYZN Netra — Camera Quota & Manual UPI Billing Migration
-- Migration: 001_camera_quota_and_orders.sql
-- ==============================================================================

-- 1. Camera Quota Table
-- Tracks purchased camera quota per tenant. Available = max(purchased - used, 0).
-- Used quota is computed from the existing cameras count.
CREATE TABLE IF NOT EXISTS public.camera_quota (
    tenant_id TEXT PRIMARY KEY,
    purchased INT NOT NULL DEFAULT 0 CHECK (purchased >= 0),
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- 2. Quota Orders Table
-- Tracks camera quota purchase orders paid via manual UPI QR.
CREATE TABLE IF NOT EXISTS public.quota_orders (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    tenant_id TEXT NOT NULL,
    user_id TEXT,
    quantity INT NOT NULL CHECK (quantity > 0),
    unit_price_paise BIGINT NOT NULL,
    amount_paise BIGINT NOT NULL,
    order_code TEXT UNIQUE NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('awaiting_payment', 'submitted', 'paid', 'rejected', 'expired')) DEFAULT 'awaiting_payment',
    utr TEXT UNIQUE,
    submitted_at TIMESTAMPTZ,
    verified_by TEXT,
    verified_at TIMESTAMPTZ,
    reject_reason TEXT,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Partial unique index: a tenant can have at most ONE order in awaiting_payment or submitted
CREATE UNIQUE INDEX IF NOT EXISTS idx_open_quota_orders_per_tenant 
    ON public.quota_orders (tenant_id) 
    WHERE status IN ('awaiting_payment', 'submitted');

CREATE INDEX IF NOT EXISTS idx_quota_orders_tenant ON public.quota_orders (tenant_id);
CREATE INDEX IF NOT EXISTS idx_quota_orders_status ON public.quota_orders (status);
CREATE INDEX IF NOT EXISTS idx_quota_orders_utr ON public.quota_orders (utr) WHERE utr IS NOT NULL;

-- 3. Payment Audit Table
-- Logs every payment state change immutably.
CREATE TABLE IF NOT EXISTS public.payment_audit (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    order_id TEXT NOT NULL REFERENCES public.quota_orders(id) ON DELETE CASCADE,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    detail TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_payment_audit_order ON public.payment_audit (order_id);

-- 4. Row Level Security (RLS)
ALTER TABLE public.camera_quota ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.quota_orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.payment_audit ENABLE ROW LEVEL SECURITY;

-- Tenants can read only their own quota
CREATE POLICY "Tenants read own quota"
    ON public.camera_quota
    FOR SELECT
    TO authenticated, anon
    USING (
        tenant_id = auth.jwt()->'app_metadata'->>'tenant_id'
        OR tenant_id = auth.uid()::text
    );

-- Service role has full access to camera_quota
CREATE POLICY "Service role full access on camera_quota"
    ON public.camera_quota
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- Tenants can read only their own orders
CREATE POLICY "Tenants read own orders"
    ON public.quota_orders
    FOR SELECT
    TO authenticated, anon
    USING (
        tenant_id = auth.jwt()->'app_metadata'->>'tenant_id'
        OR tenant_id = auth.uid()::text
    );

-- Service role has full access to quota_orders
CREATE POLICY "Service role full access on quota_orders"
    ON public.quota_orders
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- Service role has full access to payment_audit
CREATE POLICY "Service role full access on payment_audit"
    ON public.payment_audit
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- 5. Backfill Migration
-- For every existing tenant, purchased = their current camera count,
-- so nothing breaks when enforcement is turned on.
DO $$
BEGIN
    -- If tenants table exists
    IF EXISTS (SELECT FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'tenants') THEN
        INSERT INTO public.camera_quota (tenant_id, purchased)
        SELECT 
            t.id::text,
            COALESCE(COUNT(c.id), 0)
        FROM public.tenants t
        LEFT JOIN public.sites s ON s.tenant_id = t.id
        LEFT JOIN public.cameras c ON c.site_id = s.id
        GROUP BY t.id
        ON CONFLICT (tenant_id) DO UPDATE
        SET purchased = EXCLUDED.purchased;
    END IF;

    -- If vyzn_users table exists
    IF EXISTS (SELECT FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'vyzn_users') THEN
        INSERT INTO public.camera_quota (tenant_id, purchased)
        SELECT 
            u.id,
            0
        FROM public.vyzn_users u
        ON CONFLICT (tenant_id) DO NOTHING;
    END IF;
END $$;
