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

create table if not exists question (
  id bigserial primary key,
  exam varchar(80) not null,
  subject varchar(120),
  topic varchar(160),
  question_text text not null,
  answer_text text,
  difficulty varchar(20) default 'medium',
  is_public boolean default true,
  created_at timestamp without time zone default now()
);

create table if not exists question_attempt (
  id bigserial primary key,
  score integer default 0,
  notes varchar(400),
  attempted_at timestamp without time zone default now(),
  user_id bigint not null references "user"(id) on delete cascade,
  question_id bigint not null references question(id) on delete cascade
);

create table if not exists pyq_completion (
  id bigserial primary key,
  exam varchar(120) not null,
  year integer not null,
  completed_at timestamp without time zone default now(),
  user_id bigint not null references "user"(id) on delete cascade,
  roadmap_id bigint not null references roadmap(id) on delete cascade
);

create index if not exists idx_pyq_user on pyq_completion(user_id);

create table if not exists mock_test_schedule (
  id bigserial primary key,
  title varchar(160) not null,
  test_type varchar(30) default 'mock',
  scheduled_date date not null,
  duration_minutes integer default 90,
  questions_count integer default 50,
  status varchar(20) default 'planned',
  score double precision,
  notes text,
  created_at timestamp without time zone default now(),
  roadmap_id bigint not null references roadmap(id) on delete cascade
);

create index if not exists idx_mock_roadmap on mock_test_schedule(roadmap_id);

create table if not exists quiz_result (
  id bigserial primary key,
  total_questions integer default 0,
  correct integer default 0,
  incorrect integer default 0,
  score double precision default 0,
  attempted_at timestamp without time zone default now(),
  user_id bigint not null references "user"(id) on delete cascade,
  roadmap_id bigint not null references roadmap(id) on delete cascade
);

create index if not exists idx_quiz_user on quiz_result(user_id);

create index if not exists idx_question_exam on question(exam);
create index if not exists idx_attempt_user on question_attempt(user_id);

create index if not exists idx_roadmap_user_id on roadmap(user_id);
create index if not exists idx_task_roadmap_id on task(roadmap_id);
create index if not exists idx_resource_task_id on resource(task_id);
create index if not exists idx_feedback_resource_id on resource_feedback(resource_id);
create index if not exists idx_checkin_roadmap_id on checkin(roadmap_id);

-- Security hardening for Supabase API exposure
-- This app uses server-side Flask + direct database access, so these tables
-- should not be readable from the public PostgREST API by default.

alter table "user" enable row level security;
alter table roadmap enable row level security;
alter table task enable row level security;
alter table resource enable row level security;
alter table resource_feedback enable row level security;
alter table checkin enable row level security;
alter table question enable row level security;
alter table question_attempt enable row level security;
alter table pyq_completion enable row level security;
alter table mock_test_schedule enable row level security;
alter table quiz_result enable row level security;

revoke all on table "user" from anon, authenticated;
revoke all on table roadmap from anon, authenticated;
revoke all on table task from anon, authenticated;
revoke all on table resource from anon, authenticated;
revoke all on table resource_feedback from anon, authenticated;
revoke all on table checkin from anon, authenticated;
revoke all on table question from anon, authenticated;
revoke all on table question_attempt from anon, authenticated;
revoke all on table pyq_completion from anon, authenticated;
revoke all on table mock_test_schedule from anon, authenticated;
revoke all on table quiz_result from anon, authenticated;

-- If you later want public API access for selected records, add explicit RLS
-- policies then grant only the minimum required privileges back.
