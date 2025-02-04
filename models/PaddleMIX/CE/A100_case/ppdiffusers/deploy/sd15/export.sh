#!/bin/bash

log_dir=${root_path}/deploy_log

if [ ! -d "$log_dir" ]; then
    mkdir -p "$log_dir"
fi

exit_code=0

export USE_PPXFORMERS=False
(python export_model.py \
    --pretrained_model_name_or_path runwayml/stable-diffusion-v1-5 \
    --output_path static_model/stable-diffusion-v1-5) 2>&1 | tee ${log_dir}/sd15_export_model.log
tmp_exit_code=${PIPESTATUS[0]}
exit_code=$(($exit_code + ${tmp_exit_code}))
if [ ${tmp_exit_code} -eq 0 ]; then
    echo "ppdiffusers/deploy/sd15 sd15_export_model success" >>"${log_dir}/ce_res.log"
else
    echo "ppdiffusers/deploy/sd15 sd15_export_model fail" >>"${log_dir}/ce_res.log"
fi
echo "*******ppdiffusers/deploy/sd15 sd15_export_model end***********"

echo exit_code:${exit_code}
exit ${exit_code}
