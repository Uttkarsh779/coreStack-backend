(* gee_cli.ml
 * Command line interface for the OCaml Earth Engine change detection client.
 *
 * Usage:
 *   gee_cli --action <raster|vector|status> \
 *           --access-token <token>           \
 *           --project <gcp-project-id>       \
 *           --gee-asset-root <root_path>     \
 *           --state <state>                  \
 *           --district <district>            \
 *           --block <block>                  \
 *           --start-year <year>              \
 *           --end-year <year>                \
 *           [--task-id <id>]                 \
 *           [--poll]                         \
 *           [--poll-interval <seconds>]
 *
 * The --access-token is obtained by the Python caller before invoking this
 * CLI (using existing google-auth libraries), avoiding RSA JWT in OCaml.
 *)

let () =
  let action       = ref "raster" in
  let access_token = ref "" in
  let project      = ref "" in
  let gee_root     = ref "" in
  let state        = ref "" in
  let district     = ref "" in
  let block        = ref "" in
  let start_year   = ref 0 in
  let end_year     = ref 0 in
  let task_id_arg  = ref "" in
  let do_poll      = ref false in
  let poll_interval = ref 60.0 in

  let spec = Arg.align [
    ("--action",        Arg.Set_string action,
     " Action: raster | vector | status | poll");
    ("--access-token",  Arg.Set_string access_token,
     " OAuth Bearer token (obtained from Python wrapper)");
    ("--project",       Arg.Set_string project,
     " GCP project ID (e.g. my-ee-project)");
    ("--gee-asset-root", Arg.Set_string gee_root,
     " GEE asset root path (e.g. projects/my-proj/assets/core-stack/)");
    ("--state",         Arg.Set_string state,    " State name");
    ("--district",      Arg.Set_string district, " District name");
    ("--block",         Arg.Set_string block,    " Block/tehsil name");
    ("--start-year",    Arg.Set_int start_year,  " Start year (inclusive)");
    ("--end-year",      Arg.Set_int end_year,    " End year (inclusive)");
    ("--task-id",       Arg.Set_string task_id_arg,
     " GEE operation task ID (for status / poll actions)");
    ("--poll",          Arg.Set do_poll,
     " Poll until all tasks complete (blocks)");
    ("--poll-interval", Arg.Set_float poll_interval,
     " Polling interval in seconds (default 60)");
  ] in
  Arg.parse spec (fun _ -> ()) "GEE Change Detection CLI";

  (* Validate required args *)
  let require name v =
    if !v = "" then (
      Printf.eprintf "Error: --%s is required\n" name;
      exit 1
    )
  in
  let require_int name v =
    if !v = 0 then (
      Printf.eprintf "Error: --%s is required\n" name;
      exit 1
    )
  in

  (match !action with
  | "raster" | "vector" ->
      require "access-token"  access_token;
      require "project"        project;
      require "gee-asset-root" gee_root;
      require "state"          state;
      require "district"       district;
      require "block"          block;
      require_int "start-year" start_year;
      require_int "end-year"   end_year
  | "status" | "poll" ->
      require "access-token" access_token;
      require "project"       project;
      if !task_id_arg = "" then (
        Printf.eprintf "Error: --task-id is required for status/poll action\n";
        exit 1
      )
  | a ->
      Printf.eprintf "Unknown action: %s\n" a;
      exit 1);

  match !action with
  | "raster" ->
      Printf.printf "[GEE CLI] Running get_change_detection ...\n%!";
      let task_ids = Change_detection.get_change_detection
        ~access_token:!access_token
        ~project:!project
        ~gee_asset_root:!gee_root
        ~state:!state
        ~district:!district
        ~block:!block
        ~start_year:!start_year
        ~end_year:!end_year
      in
      if !do_poll then (
        Printf.printf "[GEE CLI] Polling %d tasks (interval %.0fs) ...\n%!"
          (List.length task_ids) !poll_interval;
        List.iter (fun tid ->
          let _result = Gee_sdk.poll_task
            ~access_token:!access_token
            ~project:!project
            ~task_id:tid
            ~sleep_s:!poll_interval
          in ()
        ) task_ids
      ) else (
        (* Print task IDs to stdout so Python wrapper can parse them *)
        List.iter (fun tid -> print_endline tid) task_ids
      )

  | "vector" ->
      Printf.printf "[GEE CLI] Running vectorise_change_detection ...\n%!";
      let task_ids = Change_detection_vector.vectorise_change_detection
        ~access_token:!access_token
        ~project:!project
        ~gee_asset_root:!gee_root
        ~state:!state
        ~district:!district
        ~block:!block
        ~start_year:!start_year
        ~end_year:!end_year
      in
      if !do_poll then (
        Printf.printf "[GEE CLI] Polling %d tasks (interval %.0fs) ...\n%!"
          (List.length task_ids) !poll_interval;
        List.iter (fun tid ->
          let _result = Gee_sdk.poll_task
            ~access_token:!access_token
            ~project:!project
            ~task_id:tid
            ~sleep_s:!poll_interval
          in ()
        ) task_ids
      ) else (
        List.iter (fun tid -> print_endline tid) task_ids
      )

  | "status" ->
      (match Gee_sdk.get_task_status
        ~access_token:!access_token
        ~project:!project
        ~task_id:!task_id_arg
      with
      | Ok state_str  -> Printf.printf "%s\n" state_str
      | Error e -> Printf.eprintf "Error: %s\n" e; exit 1)

  | "poll" ->
      Printf.printf "[GEE CLI] Polling task %s ...\n%!" !task_id_arg;
      (match Gee_sdk.poll_task
        ~access_token:!access_token
        ~project:!project
        ~task_id:!task_id_arg
        ~sleep_s:!poll_interval
      with
      | `Done s   -> Printf.printf "DONE: %s\n" s
      | `Failed s -> Printf.printf "FAILED: %s\n" s; exit 1
      | `Error e  -> Printf.eprintf "ERROR: %s\n" e; exit 1)

  | _ -> ()
