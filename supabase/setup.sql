-- Supabase setup script for Dreams into Reality
-- Run in Supabase SQL editor

create table if not exists "user" (
  id bigserial primary key,
  email varchar(150) unique not null,
  password varchar(256) not null
);

create table if not exists roadmap (
  id bigserial primary key,
  title varchar(180) not null,
  roadmap_type varchar(40) not null,
  source_text text,
  start_date date not null,
  target_date date not null,
  total_tasks integer default 0,
  completed_tasks integer default 0,
  total_hours_est double precision default 0,
  hours_per_week integer default 6,
  study_days_per_week integer default 5,
  timezone varchar(60) default 'Asia/Kolkata',
  streak integer default 0,
  last_checkin_date date,
  resource_fetch_status varchar(20) default 'idle',
  resource_fetch_started_at timestamp without time zone,
  resource_fetch_completed_at timestamp without time zone,
  created_at timestamp without time zone default now(),
  updated_at timestamp without time zone default now(),
  user_id bigint not null references "user"(id) on delete cascade
);

create table if not exists task (
  id bigserial primary key,
  title varchar(220) not null,
  order_index integer default 0,
  due_date date,
  status varchar(20) default 'todo',
  difficulty varchar(20) default 'medium',
  estimated_hours double precision default 1.5,
  actual_hours double precision default 0,
  completion_type varchar(20) default 'planned',
  completed_at timestamp without time zone,
  notes text,
  evidence_path varchar(400),
  last_resource_refresh timestamp without time zone,
  created_at timestamp without time zone default now(),
  updated_at timestamp without time zone default now(),
  roadmap_id bigint not null references roadmap(id) on delete cascade
);

create table if not exists resource (
  id bigserial primary key,
  provider varchar(40) not null,
  title varchar(220) not null,
  url varchar(600) not null,
  summary text,
  score double precision default 0,
  rating_avg double precision default 0,
  rating_count integer default 0,
  flagged_count integer default 0,
  task_id bigint not null references task(id) on delete cascade
);

create table if not exists resource_feedback (
  id bigserial primary key,
  rating integer,
  flagged boolean default false,
  comment varchar(300),
  created_at timestamp without time zone default now(),
  resource_id bigint not null references resource(id) on delete cascade
);

create table if not exists checkin (
  id bigserial primary key,
  checkin_date date not null,
  minutes integer default 0,
  note varchar(300),
  created_at timestamp without time zone default now(),
  roadmap_id bigint not null references roadmap(id) on delete cascade
);

create index if not exists idx_roadmap_user_id on roadmap(user_id);
create index if not exists idx_task_roadmap_id on task(roadmap_id);
create index if not exists idx_resource_task_id on resource(task_id);
create index if not exists idx_feedback_resource_id on resource_feedback(resource_id);
create index if not exists idx_checkin_roadmap_id on checkin(roadmap_id);
