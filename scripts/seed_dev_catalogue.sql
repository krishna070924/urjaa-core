-- Dev/sample catalogue configuration for urjaa.
--
-- NOT a migration and NOT production data: realistic sample values for an
-- Indian fine-jewellery store so the admin and storefront have something to
-- work against. The owner will replace values before go-live.
--
-- Run against an EMPTY catalogue:
--   docker exec -i urjaa_postgres psql -U postgres -d urjaa -v ON_ERROR_STOP=1 \
--     < scripts/seed_dev_catalogue.sql
-- (`-i` is required — without it stdin is not attached and nothing runs.)

BEGIN;

DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM base_metals) OR EXISTS (SELECT 1 FROM categories) THEN
    RAISE EXCEPTION 'Catalogue is not empty — refusing to seed over existing data';
  END IF;
END $$;

-- ── Metals ──────────────────────────────────────────────────────────────
-- Rates are per gram of PURE metal; purity scales them
-- (price = weight × rate × numeric_purity/100 + stones + making).
INSERT INTO base_metals (name) VALUES ('Gold'), ('Silver'), ('Platinum');

INSERT INTO metal_colors (name, base_metal_id)
SELECT c, bm.id FROM base_metals bm
JOIN (VALUES ('Gold','Yellow'),('Gold','White'),('Gold','Rose'),
             ('Silver','Silver'),('Platinum','Natural')) v(m,c) ON v.m = bm.name;

-- numeric_purity is a percentage (22K = 91.6%), matching PricingService.
INSERT INTO metal_purities (base_metal_id, purity_label, numeric_purity)
SELECT bm.id, p, n FROM base_metals bm
JOIN (VALUES ('Gold','24K',99.9),('Gold','22K',91.6),('Gold','18K',75.0),('Gold','14K',58.5),
             ('Silver','925',92.5),('Silver','999',99.9),
             ('Platinum','950',95.0)) v(m,p,n) ON v.m = bm.name;

INSERT INTO metal_rates (base_metal_id, rate_per_gram, effective_from)
SELECT bm.id, r, now() FROM base_metals bm
JOIN (VALUES ('Gold',9500.00),('Silver',110.00),('Platinum',3200.00)) v(m,r) ON v.m = bm.name;

-- Valid combinations only (decision D25/D26). 24K is too soft for set pieces
-- and 22K is rarely made in white or rose, so those are omitted.
INSERT INTO metals (base_metal_id, metal_color_id, metal_purity_id, display_name)
SELECT bm.id, mc.id, mp.id, mp.purity_label || ' ' || mc.name || ' ' || bm.name
FROM (VALUES ('Gold','Yellow','22K'),('Gold','Yellow','18K'),('Gold','White','18K'),
             ('Gold','Rose','18K'),('Gold','Yellow','14K'),('Gold','White','14K'),
             ('Gold','Rose','14K'),('Silver','Silver','925'),('Platinum','Natural','950')) v(m,c,p)
JOIN base_metals bm ON bm.name = v.m
JOIN metal_colors mc ON mc.name = v.c AND mc.base_metal_id = bm.id
JOIN metal_purities mp ON mp.purity_label = v.p AND mp.base_metal_id = bm.id;

-- Silver and platinum display names read better without the colour.
UPDATE metals m SET display_name = mp.purity_label || ' ' || bm.name
FROM base_metals bm, metal_purities mp
WHERE m.base_metal_id = bm.id AND m.metal_purity_id = mp.id AND bm.name IN ('Silver','Platinum');

-- ── Categories and subcategories ────────────────────────────────────────
-- size_label/size_unit (D21): what the variant's size_value is CALLED here.
-- Null means that subcategory does not vary by size.
INSERT INTO categories (name, slug, display_order) VALUES
  ('Rings','rings',1), ('Necklaces','necklaces',2), ('Earrings','earrings',3),
  ('Bangles & Bracelets','bangles-bracelets',4), ('Pendants','pendants',5),
  ('Chains','chains',6), ('Mangalsutra','mangalsutra',7);

INSERT INTO subcategories (category_id, name, slug, size_label, size_unit)
SELECT c.id, s, sl, lbl, unit FROM categories c
JOIN (VALUES
  ('rings','Engagement Rings','engagement-rings','Ring Size','IN'),
  ('rings','Wedding Bands','wedding-bands','Ring Size','IN'),
  ('rings','Cocktail Rings','cocktail-rings','Ring Size','IN'),
  ('necklaces','Chokers','chokers','Length','inches'),
  ('necklaces','Long Necklaces','long-necklaces','Length','inches'),
  ('necklaces','Bridal Sets','bridal-sets',NULL,NULL),
  ('earrings','Studs','studs',NULL,NULL),
  ('earrings','Jhumkas','jhumkas',NULL,NULL),
  ('earrings','Hoops','hoops',NULL,NULL),
  ('bangles-bracelets','Bangles','bangles','Bangle Size','inches'),
  ('bangles-bracelets','Kadas','kadas','Bangle Size','inches'),
  ('bangles-bracelets','Bracelets','bracelets','Length','inches'),
  ('pendants','Solitaire Pendants','solitaire-pendants',NULL,NULL),
  ('pendants','Religious Pendants','religious-pendants',NULL,NULL),
  ('chains','Gold Chains','gold-chains','Length','inches'),
  ('mangalsutra','Mangalsutra','mangalsutra-classic','Length','inches')
) v(cs,s,sl,lbl,unit) ON v.cs = c.slug;

-- ── Stones, tags, collections ───────────────────────────────────────────
INSERT INTO stones (name, stone_group) VALUES
  ('Diamond','Precious'), ('Polki','Precious'), ('Ruby','Precious'),
  ('Emerald','Precious'), ('Blue Sapphire','Precious'), ('Kundan','Traditional'),
  ('Pearl','Organic'), ('Amethyst','Semi-precious'), ('Citrine','Semi-precious'),
  ('Garnet','Semi-precious');

INSERT INTO tags (name, slug) VALUES
  ('New Arrival','new-arrival'), ('Bestseller','bestseller'), ('Sale','sale'),
  ('Featured','featured'), ('Handcrafted','handcrafted'),
  ('Lightweight','lightweight'), ('Gift','gift');

-- Names from the storefront design's collections nav.
INSERT INTO collections (name, slug, description, is_featured, display_order) VALUES
  ('Bridal','bridal','Heirloom pieces for the wedding day.',true,1),
  ('Noor','noor','Polki and uncut diamonds in 22K gold.',true,2),
  ('Chandrika','chandrika','Moonlit silhouettes in white gold and diamonds.',true,3),
  ('Meher','meher','Everyday fine jewellery.',false,4),
  ('Gulmohar','gulmohar','Rubies and rose gold.',false,5),
  ('Aabha','aabha','Contemporary solitaires.',false,6);

-- ── Showrooms (contact page, appointment booking) ───────────────────────
INSERT INTO store_locations (id, store_id, address, city, state, pincode, phone, hours)
SELECT gen_random_uuid(), s.id, v.a, v.c, v.st, v.p, v.ph,
       '{"mon-sat":"11:00-20:00","sun":"12:00-18:00"}'::jsonb
FROM stores s,
(VALUES ('Altamount Road, Cumballa Hill','Mumbai','Maharashtra','400026','+91 22 4000 1000'),
        ('Khan Market','New Delhi','Delhi','110003','+91 11 4000 2000')) v(a,c,st,p,ph)
LIMIT 2;

COMMIT;
