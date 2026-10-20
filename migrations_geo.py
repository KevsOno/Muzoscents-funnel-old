# migrations_geo.py
import httpx

from deps import (
    SUPABASE_URL,
    SUPABASE_SERVICE_ROLE_KEY,
    SUPABASE_ANON_KEY,
    logger,
)

_SRK = SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY


async def _exec_sql(sql: str):
    headers = {
        "apikey": _SRK,
        "Authorization": f"Bearer {_SRK}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{SUPABASE_URL}/rest/v1/rpc/exec_sql",
            json={"query": sql},
            headers=headers,
        )
    if resp.status_code not in (200, 204):
        logger.error(f"Geo migration failed: {resp.text}")
        raise RuntimeError(f"Geo migration failed: {resp.text}")


async def ensure_geo_schema():
    """
    Idempotent additive migration for geospatial, dispatch, and zones.
    Safe to run on every boot.
    """
    # 1. Enable PostGIS
    await _exec_sql("CREATE EXTENSION IF NOT EXISTS postgis;")

    # 2. Delivery Zones Tables
    await _exec_sql("""
    CREATE TABLE IF NOT EXISTS public.delivery_areas (
        id SERIAL PRIMARY KEY,
        org_id UUID NOT NULL REFERENCES public.organisations(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        fee INTEGER NOT NULL DEFAULT 0,
        polygon geometry(Polygon, 4326) NOT NULL,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );
    
    CREATE TABLE IF NOT EXISTS public.delivery_fee_rules (
        id SERIAL PRIMARY KEY,
        org_id UUID NOT NULL REFERENCES public.organisations(id) ON DELETE CASCADE,
        min_order_value INTEGER NOT NULL,
        max_order_value INTEGER,
        fee_multiplier NUMERIC DEFAULT 1.0,
        fee_discount INTEGER DEFAULT 0,
        free_delivery BOOLEAN DEFAULT FALSE,
        description TEXT,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );
    
    CREATE TABLE IF NOT EXISTS public.delivery_peak_settings (
        id SERIAL PRIMARY KEY,
        org_id UUID NOT NULL REFERENCES public.organisations(id) ON DELETE CASCADE,
        day_of_week INTEGER,
        start_time TIME,
        end_time TIME,
        surcharge_amount INTEGER DEFAULT 200,
        is_active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );
    
    CREATE TABLE IF NOT EXISTS public.delivery_loyalty_settings (
        id SERIAL PRIMARY KEY,
        org_id UUID NOT NULL REFERENCES public.organisations(id) ON DELETE CASCADE,
        min_orders INTEGER DEFAULT 5,
        discount_percentage INTEGER DEFAULT 20,
        is_active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );
    
    CREATE TABLE IF NOT EXISTS public.delivery_item_surcharge_rules (
        id SERIAL PRIMARY KEY,
        org_id UUID NOT NULL REFERENCES public.organisations(id) ON DELETE CASCADE,
        min_main_items INTEGER,
        max_main_items INTEGER,
        surcharge_amount INTEGER DEFAULT 0,
        weight_threshold_kg NUMERIC(6,2),
        surcharge_per_kg INTEGER,
        description TEXT,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );
    """)

    # 3. Dispatch & Tracking Tables
    await _exec_sql("""
    CREATE TABLE IF NOT EXISTS public.driver_locations (
        org_id UUID NOT NULL REFERENCES public.organisations(id) ON DELETE CASCADE,
        driver_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
        branch_id UUID REFERENCES public.branches(id) ON DELETE RESTRICT,
        lat DOUBLE PRECISION NOT NULL CHECK (lat >= -90 AND lat <= 90),
        lng DOUBLE PRECISION NOT NULL CHECK (lng >= -180 AND lng <= 180),
        accuracy DOUBLE PRECISION,
        battery INTEGER CHECK (battery >= 0 AND battery <= 100),
        is_charging BOOLEAN,
        updated_at TIMESTAMPTZ DEFAULT now(),
        PRIMARY KEY (org_id, driver_id)
    );

    CREATE TABLE IF NOT EXISTS public.geofences (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        org_id UUID NOT NULL REFERENCES public.organisations(id) ON DELETE CASCADE,
        branch_id UUID REFERENCES public.branches(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        description TEXT,
        polygon JSONB NOT NULL,
        aws_geofence_id TEXT UNIQUE,
        is_active BOOLEAN DEFAULT TRUE,
        color TEXT DEFAULT '#E53935',
        kind TEXT DEFAULT 'coverage',
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS public.geofence_events (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        org_id UUID NOT NULL REFERENCES public.organisations(id) ON DELETE CASCADE,
        geofence_id UUID REFERENCES public.geofences(id) ON DELETE CASCADE,
        driver_id UUID REFERENCES public.profiles(id) ON DELETE CASCADE,
        event_type TEXT NOT NULL CHECK (event_type IN ('enter', 'exit')),
        lat DOUBLE PRECISION NOT NULL,
        lng DOUBLE PRECISION NOT NULL,
        aws_event_id TEXT UNIQUE,
        occurred_at TIMESTAMPTZ DEFAULT NOW(),
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    """)

    # 4. Sale Events (Audit Trail) & Sales Columns
    await _exec_sql("""
    CREATE TABLE IF NOT EXISTS public.sale_events (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        org_id UUID NOT NULL REFERENCES public.organisations(id) ON DELETE CASCADE,
        sale_id UUID NOT NULL REFERENCES public.sales(id) ON DELETE CASCADE,
        from_status TEXT,
        to_status TEXT NOT NULL,
        changed_by UUID REFERENCES public.profiles(id),
        created_at TIMESTAMPTZ DEFAULT NOW()
    );

    ALTER TABLE public.sales 
        ADD COLUMN IF NOT EXISTS delivery_lat DOUBLE PRECISION,
        ADD COLUMN IF NOT EXISTS delivery_lng DOUBLE PRECISION,
        ADD COLUMN IF NOT EXISTS delivery_breakdown JSONB,
        ADD COLUMN IF NOT EXISTS assigned_driver_id UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
        ADD COLUMN IF NOT EXISTS picked_at TIMESTAMPTZ,
        ADD COLUMN IF NOT EXISTS dispatched_at TIMESTAMPTZ,
        ADD COLUMN IF NOT EXISTS delivered_at TIMESTAMPTZ;
    """)

    # 5. RPCs (Org-Scoped Rewrites)
    await _exec_sql("""
    -- Drop old signatures to allow clean recreation
    DROP FUNCTION IF EXISTS public.find_delivery_area(uuid, double precision, double precision);
    DROP FUNCTION IF EXISTS public.get_delivery_areas_geojson(uuid);
    DROP FUNCTION IF EXISTS public.insert_delivery_area(uuid, text, integer, text);
    DROP FUNCTION IF EXISTS public.update_delivery_area(integer, uuid, text, integer, text);

    CREATE OR REPLACE FUNCTION public.find_delivery_area(
        p_org_id uuid,
        p_lat double precision,
        p_lng double precision
    )
    RETURNS TABLE(id integer, name text, fee integer)
    LANGUAGE plpgsql
    AS $$
    BEGIN
        RETURN QUERY
        SELECT da.id, da.name, da.fee
        FROM public.delivery_areas da
        WHERE da.org_id = p_org_id
          AND ST_Contains(
              da.polygon,
              ST_SetSRID(ST_MakePoint(p_lng, p_lat), 4326)
          )
        LIMIT 1;
    END;
    $$;

    CREATE OR REPLACE FUNCTION public.get_delivery_areas_geojson(p_org_id uuid)
    RETURNS TABLE(id integer, name text, fee integer, polygon jsonb, created_at timestamptz, updated_at timestamptz)
    LANGUAGE plpgsql
    AS $$
    BEGIN
        RETURN QUERY
        SELECT da.id, da.name, da.fee, ST_AsGeoJSON(da.polygon)::jsonb, da.created_at, da.updated_at
        FROM public.delivery_areas da
        WHERE da.org_id = p_org_id
        ORDER BY da.id;
    END;
    $$;

    CREATE OR REPLACE FUNCTION public.insert_delivery_area(
        p_org_id uuid,
        p_name text,
        p_fee integer,
        p_geojson text
    )
    RETURNS TABLE(id integer, name text, fee integer, polygon jsonb, created_at timestamptz, updated_at timestamptz)
    LANGUAGE plpgsql
    AS $$
    DECLARE
        v_geom geometry;
        v_result RECORD;
    BEGIN
        v_geom := ST_SetSRID(ST_GeomFromGeoJSON(p_geojson), 4326);
        IF ST_GeometryType(v_geom) != 'ST_Polygon' THEN
            RAISE EXCEPTION 'Geometry must be a Polygon';
        END IF;
        
        INSERT INTO public.delivery_areas (org_id, name, fee, polygon, created_at, updated_at)
        VALUES (p_org_id, p_name, p_fee, v_geom, NOW(), NOW())
        RETURNING delivery_areas.id, delivery_areas.name, delivery_areas.fee, 
                  delivery_areas.polygon, delivery_areas.created_at, delivery_areas.updated_at 
        INTO v_result;
        
        RETURN QUERY SELECT 
            v_result.id, v_result.name, v_result.fee, 
            ST_AsGeoJSON(v_result.polygon)::jsonb, v_result.created_at, v_result.updated_at;
    END;
    $$;

    CREATE OR REPLACE FUNCTION public.update_delivery_area(
        p_id integer,
        p_org_id uuid,
        p_name text,
        p_fee integer,
        p_geojson text
    )
    RETURNS TABLE(id integer, name text, fee integer, polygon jsonb, created_at timestamptz, updated_at timestamptz)
    LANGUAGE plpgsql
    AS $$
    DECLARE
        v_geom geometry;
        v_result RECORD;
    BEGIN
        v_geom := ST_SetSRID(ST_GeomFromGeoJSON(p_geojson), 4326);
        IF ST_GeometryType(v_geom) != 'ST_Polygon' THEN
            RAISE EXCEPTION 'Geometry must be a Polygon';
        END IF;
        
        UPDATE public.delivery_areas
        SET name = p_name, fee = p_fee, polygon = v_geom, updated_at = NOW()
        WHERE id = p_id AND org_id = p_org_id
        RETURNING delivery_areas.id, delivery_areas.name, delivery_areas.fee, 
                  delivery_areas.polygon, delivery_areas.created_at, delivery_areas.updated_at 
        INTO v_result;
        
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Delivery area with ID % not found in this org', p_id;
        END IF;
        
        RETURN QUERY SELECT 
            v_result.id, v_result.name, v_result.fee, 
            ST_AsGeoJSON(v_result.polygon)::jsonb, v_result.created_at, v_result.updated_at;
    END;
    $$;
    """)

    # 6. Realtime Publication
    await _exec_sql("""
    DO $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_publication_tables WHERE pubname='supabase_realtime' AND tablename='driver_locations') THEN
            ALTER PUBLICATION supabase_realtime ADD TABLE public.driver_locations;
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_publication_tables WHERE pubname='supabase_realtime' AND tablename='geofences') THEN
            ALTER PUBLICATION supabase_realtime ADD TABLE public.geofences;
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_publication_tables WHERE pubname='supabase_realtime' AND tablename='geofence_events') THEN
            ALTER PUBLICATION supabase_realtime ADD TABLE public.geofence_events;
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_publication_tables WHERE pubname='supabase_realtime' AND tablename='sales') THEN
            ALTER PUBLICATION supabase_realtime ADD TABLE public.sales;
        END IF;
    END $$;
    """)

    logger.info("Geospatial and Dispatch schema installed successfully.")
