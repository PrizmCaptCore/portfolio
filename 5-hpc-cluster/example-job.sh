#!/bin/bash
#SBATCH --job-name=ml_training
#SBATCH --output=/results/training_%j.log
#SBATCH --error=/results/training_%j.err
#SBATCH --partition=gpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --gres=gpu:1
#SBATCH --mem=16G
#SBATCH --time=24:00:00

# Load environment
module load python/3.9
module load cuda/11.8

# Activate virtual environment
source /opt/venv/bin/activate

# Set environment variables
export CUDA_VISIBLE_DEVICES=$SLURM_LOCALID
export OMP_NUM_THREADS=$SLURM_CPUS_PER_TASK

# Print job information
echo "Job ID: $SLURM_JOB_ID"
echo "Node: $SLURMD_NODENAME"
echo "GPUs: $CUDA_VISIBLE_DEVICES"
echo "CPUs: $SLURM_CPUS_PER_TASK"
echo "Memory: $SLURM_MEM_PER_NODE MB"

# Run training script
python3 /workspace/train_model.py \
    --data-path /data/training \
    --batch-size 32 \
    --epochs 50 \
    --output-dir /results/${SLURM_JOB_ID}

echo "Training completed"
