#!/bin/bash
source /home/uttkarsh/.opam/opam-init/init.sh > /dev/null 2> /dev/null || true
cd /home/uttkarsh/core-stack-backend/village_lulc_analytics_ocaml
eval $(opam env --switch=geocaml)
dune build
