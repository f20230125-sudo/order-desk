-- A note (severity info, such as "part delivery, balance to follow") is not a problem: the board counts
-- problems (block and warn) and notes separately.

create or replace view order_problem_counts as
select customer_order_id,
       count(*) filter (where severity in ('block', 'warn')) as problems,
       count(*) filter (where severity = 'block') as blocking,
       count(*) filter (where severity = 'info') as notes
from discrepancy
where status = 'open'
group by customer_order_id;

create or replace view board as
select oc.*,
       coalesce(pc.problems, 0)::int as problems,
       coalesce(pc.notes, 0)::int as notes,
       (select x.explanation from discrepancy x
         where x.customer_order_id = oc.id and x.status = 'open' and x.severity in ('block', 'warn')
         order by (x.severity = 'block') desc, x.id
         limit 1) as first_problem
from order_chain oc
left join order_problem_counts pc on pc.customer_order_id = oc.id;
