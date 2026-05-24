#!/usr/bin/env nix
#! nix shell nixpkgs#fish nixpkgs#kubectl nixpkgs#openssl nixpkgs#coreutils --command fish

function main -a username -a cluster -a role
    set script_dir "$(dirname (status --current-filename))"
    set private_key "$script_dir/$username.key"
    set csr "$script_dir/$username.csr"
    set cert "$script_dir/$username.crt"
    set role_bind "$script_dir/../roles/$username.yaml"
    set openssl_config "$script_dir/openssl.cnf"

    # create private key & CSR
    openssl genpkey -out "$private_key" -algorithm Ed25519
    or exit 1
    openssl req -new -key "$private_key" -out "$csr" -subj "/CN=$username/O=$cluster"
    or exit 1

    # send CSR to cluster
    echo "
apiVersion: certificates.k8s.io/v1
kind: CertificateSigningRequest
metadata:
  name: $username
spec:
  request: $(cat "$csr" | base64 | tr -d '\n')
  signerName: kubernetes.io/kube-apiserver-client
  usages:
    - client auth
" \
        | kubectl apply -f -

    # approve the CSR
    kubectl certificate approve "$username"

    kubectl get csr "$username" -o jsonpath='{.status.certificate}' | base64 -d >"$cert"

    # clean up the CSR
    kubectl delete csr "$username"

    # bind role to the new user
    echo "---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: '$username-$role'
subjects:
  - kind: User
    name: '$username'
    apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: ClusterRole
  name: '$role'
  apiGroup: rbac.authorization.k8s.io" >"$role_bind"

    # unstage all changes
    git reset
    # stage new resources
    git add "$role_bind"

    # ask user to verify staged changes
    git diff --cached
    read -l -P 'Does the above diff look correct? Can we commit and push? [y/s/N] ' confirm
    switch $confirm
        case Y y yes
            echo continuing
            # commit & push changes
            git commit -m "🛂 add user $username to cluster $cluster as $role"
            git push
            echo ""
        case S s skip
            echo skipping
        case '*'
            echo aborting
            exit
    end

    echo "Now transfer '$private_key' & '$cert' to your client computer, and run the following to configure kubectl:"
    echo "kubectl config set-credentials '$username' \\
        --client-key='$private_key' \\
        --client-certificate='$cert' \\
        --embed-certs=true"
end

set username "$argv[1]"
if string match -q -- '-*' "$username"
    echo "error: username must not start with '-'"
    exit 1
end
if test -z "$username"
    read -gP 'username: ' username
end

set role "$argv[2]"
if test -z "$role"
    set role owner
end

main "$username" doa-cluster "$role"
