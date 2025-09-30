-- Accounts table
create table if not exists accounts (
  id uuid primary key default gen_random_uuid(),
  handle text unique not null,
  last_scraped_at timestamptz,
  created_at timestamptz default now()
);

-- Posts table
create table if not exists posts (
  id uuid primary key default gen_random_uuid(),
  account_id uuid not null references accounts(id) on delete cascade,
  post_url text unique not null,
  post_id text,
  posted_at timestamptz,
  views bigint,
  likes bigint,
  comments bigint,
  caption text,
  length_sec int,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);
create index if not exists idx_posts_account_id on posts(account_id);
create index if not exists idx_posts_posted_at on posts(posted_at);

-- Post review table
create table if not exists post_review (
  post_id uuid primary key references posts(id) on delete cascade,
  outlier boolean default false,
  keep boolean,
  reject_reason text check (reject_reason in ('IRR','NSFW','LEN','AUD','CELEB','OTH')),
  reject_notes text,
  video_file_url text,
  hook_style text,
  tone text,
  emotion text,
  editing text,
  audio text,
  why_viral text,
  yakety_hook_ideas text,
  yakety_script text,
  voiceover_url text,
  draft_video_url text,
  published_url text,
  performance_notes text,
  updated_at timestamptz default now()
);

-- Account summaries table
create table if not exists account_summaries (
  account_id uuid primary key references accounts(id) on delete cascade,
  n_posts int,
  p10_views numeric,
  p90_views numeric,
  trimmed_mean_views numeric,
  trimmed_sd_views numeric,
  last_updated timestamptz default now()
);