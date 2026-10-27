-- Storefront A: local stand-in for the catalog tables (B-029). Loaded ONLY into a throwaway local
-- cluster by scripts/local_storefront_db.py; never applied to a real storefront (PRD §18).
--
-- products, categories and tags reproduce the live structure exactly: column names, types, defaults,
-- nullability and constraints, as recorded in catalog-structure.json. Verified against Storefront A's
-- Supabase project on 2026-10-27 and its production schema dump of 2026-10-21. Columns follow the
-- Supabase project's order.
--
-- users and orders are stand-ins for the customer tables that share the real database. They exist so
-- tests can prove the read-only role can't reach them. Their columns are invented.

CREATE TABLE public.categories (
    id character varying DEFAULT gen_random_uuid() NOT NULL,
    name text NOT NULL,
    description text,
    slug text NOT NULL,
    is_active boolean DEFAULT true,
    is_featured boolean DEFAULT false,
    sort_order integer DEFAULT 0,
    created_at timestamp without time zone DEFAULT now()
);

CREATE TABLE public.products (
    id character varying DEFAULT gen_random_uuid() NOT NULL,
    name text NOT NULL,
    slug text NOT NULL,
    description text,
    short_description text,
    price numeric(10,2) NOT NULL,
    category_id character varying,
    sku text,
    status text DEFAULT 'active'::text,
    is_featured boolean DEFAULT false,
    stock integer DEFAULT 0,
    images jsonb DEFAULT '[]'::jsonb,
    dimensions text,
    medium text,
    year integer,
    is_original boolean DEFAULT false,
    rarity text,
    frame text,
    packaging text,
    authenticity text,
    show_in_gallery boolean DEFAULT false,
    is_sold boolean DEFAULT false,
    tags jsonb DEFAULT '[]'::jsonb,
    pricing_tiers jsonb DEFAULT '[]'::jsonb,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);

CREATE TABLE public.tags (
    id character varying DEFAULT gen_random_uuid() NOT NULL,
    name text NOT NULL,
    slug text NOT NULL,
    created_at timestamp without time zone DEFAULT now()
);

ALTER TABLE ONLY public.categories ADD CONSTRAINT categories_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.categories ADD CONSTRAINT categories_slug_unique UNIQUE (slug);
ALTER TABLE ONLY public.products ADD CONSTRAINT products_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.products ADD CONSTRAINT products_sku_unique UNIQUE (sku);
ALTER TABLE ONLY public.products ADD CONSTRAINT products_slug_unique UNIQUE (slug);
ALTER TABLE ONLY public.tags ADD CONSTRAINT tags_name_unique UNIQUE (name);
ALTER TABLE ONLY public.tags ADD CONSTRAINT tags_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.tags ADD CONSTRAINT tags_slug_unique UNIQUE (slug);
ALTER TABLE ONLY public.products ADD CONSTRAINT products_category_id_categories_id_fk FOREIGN KEY (category_id) REFERENCES public.categories(id);

-- Stand-ins for the customer tables (invented columns).
CREATE TABLE public.users (
    id character varying DEFAULT gen_random_uuid() PRIMARY KEY,
    email text NOT NULL UNIQUE,
    created_at timestamp without time zone DEFAULT now()
);

CREATE TABLE public.orders (
    id character varying DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id character varying REFERENCES public.users(id),
    total numeric(10,2) NOT NULL,
    created_at timestamp without time zone DEFAULT now()
);

-- Supabase lock-down, as on the real project: row-level security on for every table, with no policies.
-- The read-only role's runbook (docs/runbooks/read-only-role.md §2a) adds its own SELECT policies.
ALTER TABLE public.categories ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.products ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.tags ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.orders ENABLE ROW LEVEL SECURITY;
