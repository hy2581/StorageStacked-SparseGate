# Independent reopen of saved mapped artifact; no recompile, no changed clock.
set_app_var target_library [list $env(SG_LIBRARY)]
set_app_var link_library [list * $env(SG_LIBRARY)]
read_ddc mapped.ddc
current_design sg_index_core
link
redirect -file readback_check.rpt {check_design}
redirect -file readback_units.rpt {report_units}
redirect -file readback_setup.rpt {report_timing -delay_type max -max_paths 1 -significant_digits 6}
redirect -file readback_hold.rpt {report_timing -delay_type min -max_paths 1 -significant_digits 6}
redirect -file readback_ports.rpt {report_port -verbose -nosplit -significant_digits 6}
set timing_check_file [open readback_timing_coverage_status.txt w]
if {[catch {redirect -file readback_check_timing.rpt {check_timing -verbose -include {no_clock no_input_delay partial_input_delay unconstrained_endpoints clock_no_period}}} timing_check_error]} {
    puts $timing_check_file "status=NOT_CHECKED"
    puts $timing_check_file "reason=$timing_check_error"
} else {
    puts $timing_check_file "status=CHECKED_REQUIRES_REVIEW"
}
close $timing_check_file
set target_lib_name [file rootname [file tail $env(SG_LIBRARY)]]
set target_lib_cells [get_lib_cells -quiet ${target_lib_name}/*]
if {[sizeof_collection $target_lib_cells] == 0} {error "No cells found in the explicitly selected target library"}
set area_file [open readback_library_cell_areas.tsv w]
puts $area_file "cell\tarea_library_units"
foreach_in_collection cell $target_lib_cells {
    puts $area_file "[get_object_name $cell]\t[get_attribute $cell area]"
}
close $area_file
set leaf [get_cells -hierarchical -filter {is_hierarchical == false}]
set refs [lsort -unique [get_attribute $leaf ref_name]]
set unknown {}
foreach ref $refs {
    if {[sizeof_collection [get_lib_cells -quiet */$ref]] == 0} {lappend unknown $ref}
}
set f [open readback_mapping.txt w]
puts $f "current_design=[get_object_name [current_design]]"
puts $f "is_mapped=[get_attribute [current_design] is_mapped]"
puts $f "leaf_cells=[sizeof_collection $leaf]"
puts $f "registers=[sizeof_collection [all_registers]]"
puts $f "unbound_leaf_reference_count=[llength $unknown]"
puts $f "unbound_leaf_references=$unknown"
close $f
quit
