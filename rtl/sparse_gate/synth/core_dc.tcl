# Native SystemVerilog synthesis of the actual arithmetic core. Run in evidence dir.
set_app_var search_path [concat $search_path [file dirname $env(SG_LIBRARY)]]
set_app_var target_library [list $env(SG_LIBRARY)]
set_app_var link_library [list * $env(SG_LIBRARY)]
set_app_var synthetic_library [list dw_foundation.sldb]
define_design_lib WORK -path ./work
analyze -format sverilog [list ./source/sg_fp32_pkg.sv ./source/sg_index_core.sv]
elaborate sg_index_core
current_design sg_index_core
link
redirect -file check_elaborated.rpt {check_design}
redirect -file hierarchy.rpt {report_hierarchy}
redirect -file resources.rpt {report_resources}
redirect -file units.rpt {report_units}
write -format ddc -hierarchy -output elaborated.ddc
create_clock -name core_clk -period 2.0 [get_ports clk]
set_clock_uncertainty 0.05 [get_clocks core_clk]
set_input_delay 0.20 -clock core_clk [remove_from_collection [all_inputs] [get_ports {clk rst_n}]]
set_output_delay 0.20 -clock core_clk [all_outputs]
set_input_transition 0.05 [remove_from_collection [all_inputs] [get_ports clk]]
set_load 0.02 [all_outputs]
set_false_path -from [get_ports rst_n]
set_max_area 0
compile_ultra -no_autoungroup
redirect -file check_mapped.rpt {check_design}
redirect -file area.rpt {report_area -hierarchy}
redirect -file references.rpt {report_reference -hierarchy}
redirect -file setup.rpt {report_timing -delay_type max -max_paths 10 -nworst 1 -significant_digits 6}
redirect -file hold.rpt {report_timing -delay_type min -max_paths 10 -nworst 1 -significant_digits 6}
redirect -file violations.rpt {report_constraint -all_violators -significant_digits 6}
redirect -file qor.rpt {report_qor}
redirect -file clocks.rpt {report_clock -attributes}
set unmapped [get_cells -hierarchical -quiet -filter "ref_name =~ GTECH* || ref_name =~ *SEQGEN*"]
set status [open mapping_status.txt w]
puts $status "current_design=[get_object_name [current_design]]"
puts $status "is_mapped=[get_attribute [current_design] is_mapped]"
puts $status "gtech_or_seqgen_cells=[sizeof_collection $unmapped]"
puts $status "leaf_cells=[sizeof_collection [get_cells -hierarchical -filter {is_hierarchical == false}]]"
puts $status "registers=[sizeof_collection [all_registers]]"
close $status
write -format ddc -hierarchy -output mapped.ddc
write -format verilog -hierarchy -output mapped.v
write_sdc mapped.sdc
set complete [open completed.txt w]
puts $complete "Native DC mapping completed. Inspect mapping and timing; this is not physical signoff."
close $complete
quit
