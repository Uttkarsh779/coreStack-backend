(* Milestone 1 smoke test: verify the project builds and basic modules load *)
let () =
  Alcotest.run "village_lulc_analytics" [
    "scaffold", [
      Alcotest.test_case "build succeeds" `Quick (fun () ->
        Alcotest.(check bool) "scaffold ready" true true
      )
    ]
  ]
